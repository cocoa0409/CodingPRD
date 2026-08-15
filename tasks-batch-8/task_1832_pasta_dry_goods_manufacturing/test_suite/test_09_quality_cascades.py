"""Quality disposition and cascades: dual-dimension independence, lot
retest/reject cascade, pest quarantine cascade, gluten product-test cascade,
release gates, and immediate visibility."""
from test_helpers import (
    ApiErrorId,
    advance_run,
    complete_packaging,
    create_zone,
    get_goods_lot,
    get_packaging_job,
    get_recipe,
    get_run,
    get_zone,
    put_away,
    record_and_verify_pest_inspection,
    record_and_verify_product_test,
    record_pest_inspection,
    reject_lot,
    release_goods_lot,
    set_clock,
    setup_completed_run_with_goods_lot,
    setup_run_in_packaging,
    setup_scheduled_run,
    setup_stored_goods_lot,
    submit_lot_labs,
    validate_error,
    validate_success,
    verify_pest_inspection,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
QAM = TEST_USERS["qa_manager_headers"]
CLERK = TEST_USERS["warehouse_clerk_headers"]

WORSE_LABS = {"lab_protein_pct": 11.0, "lab_moisture_pct": 14.0,
              "lab_gluten_index": 55, "lab_falling_number_s": 240}


class TestDualDimensionIndependence:
    def test_hold_moves_disposition_while_production_stays_packaging(self, api):
        """PRD: "Run quality disposition is an independent dimension from
        production status."
        PRD: "A `QAManager` may hold a `PENDING_QA` run, moving it to `HELD`."
        PRD: "Quality release — from `PENDING_QA` or `HELD` — requires the
        run's `production_status` to be `COMPLETED` (`ERR_INVALID_STATE`)"

        Design: Difficulty/non_linear_state_machine/production_run_dual_dimension_independence
        """
        sc = setup_run_in_packaging(contract_code="C-DD", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0)
        run = sc["run"]
        assert run["production_status"] == "PACKAGING"

        held = validate_success(api.quality_hold_run(run["id"], QAM))
        assert held["quality_disposition"] == "HELD"
        assert held["production_status"] == "PACKAGING", "dimensions move independently"

        resp = api.quality_release_run(run["id"], QAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_run(run["id"])
        assert after["quality_disposition"] == "HELD", "failed release changes nothing"

    def test_held_run_releases_after_production_completes(self, api):
        """PRD: "Quality release — from `PENDING_QA` or `HELD` — requires the
        run's `production_status` to be `COMPLETED` (`ERR_INVALID_STATE`)"
        PRD: "Release moves the disposition to `RELEASED`"

        Design: Difficulty/non_linear_state_machine/production_run_dual_dimension_independence
        """
        sc = setup_run_in_packaging(contract_code="C-DD2", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0)
        validate_success(api.quality_hold_run(sc["run"]["id"], QAM))

        complete_packaging(sc["job"]["id"])
        run = advance_run(sc["run"]["id"])
        assert run["production_status"] == "COMPLETED"
        assert run["quality_disposition"] == "HELD", "hold persists through completion"

        released = validate_success(api.quality_release_run(sc["run"]["id"], QAM))
        assert released["quality_disposition"] == "RELEASED"


class TestPestCriticalCascade:
    def test_critical_from_clear_quarantines_blocks_holds(self, api):
        """PRD: "A verified `CRITICAL` — from either `CLEAR` or `MONITORING` —
        moves the zone to `QUARANTINED`, stamps `quarantined_at`, and fires a
        two-hop cascade: every lot `STORED` in the zone flips to `BLOCKED`
        while continuing to occupy its pallets, and for each lot blocked in
        that hop, its run — if still `PENDING_QA` — flips to `HELD`."

        Design: Difficulty/transitive_cascade/pest_critical_cascades_zone_lots_run_hold
        """
        sc = setup_stored_goods_lot(contract_code="C-PST", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0,
                                    zone_name="Z-PST", capacity_pallets=10)
        assert sc["run"]["quality_disposition"] == "PENDING_QA"

        record_and_verify_pest_inspection(sc["zone"]["id"], "CRITICAL",
                                          notes="rodent droppings at pallet rack")
        zone = get_zone(sc["zone"]["id"])
        assert zone["pest_posture"] == "QUARANTINED", "hop 1"
        assert zone["occupied_pallets"] == 3, "BLOCKED lots keep occupying"

        goods = get_goods_lot(sc["goods_lot"]["id"])
        assert goods["status"] == "BLOCKED", "hop 2"
        run = get_run(sc["run"]["id"])
        assert run["quality_disposition"] == "HELD", "hop 3"

    def test_critical_from_monitoring_applies_same_cascade(self, api):
        """PRD: "A verified `MINOR` moves a `CLEAR` zone to `MONITORING`"
        PRD: "A verified `CRITICAL` — from either `CLEAR` or `MONITORING` —
        moves the zone to `QUARANTINED`, stamps `quarantined_at`, and fires a
        two-hop cascade: every lot `STORED` in the zone flips to `BLOCKED`
        while continuing to occupy its pallets, and for each lot blocked in
        that hop, its run — if still `PENDING_QA` — flips to `HELD`."

        Design: Difficulty/transitive_cascade/pest_critical_cascades_zone_lots_run_hold
        """
        sc = setup_completed_run_with_goods_lot(
            contract_code="C-PST2", lot_weight_kg=3000.0, planned_input_kg=2000.0,
            actual_yield_kg=1001.0)
        zone = create_zone("Z-PST2", "CONVENTIONAL", 10)
        record_and_verify_pest_inspection(zone["id"], "MINOR")
        assert get_zone(zone["id"])["pest_posture"] == "MONITORING"
        put_away(sc["goods_lot"]["id"], zone["id"])

        record_and_verify_pest_inspection(zone["id"], "CRITICAL")
        zone = get_zone(zone["id"])
        assert zone["pest_posture"] == "QUARANTINED"
        assert zone["occupied_pallets"] == 3
        assert get_goods_lot(sc["goods_lot"]["id"])["status"] == "BLOCKED"
        assert get_run(sc["run"]["id"])["quality_disposition"] == "HELD"


class TestSemolinaRetestRejectCascade:
    def test_reject_fires_two_hop_cascade_onto_run_and_job(self, api):
        """PRD: "Rejection moves a `QUARANTINED` lot to `REJECTED` and fires a
        three-hop hold cascade, atomically: first, every production run whose
        `semolina_lot_id` names this lot, whose `production_status` is any of
        `SCHEDULED`, `MIXING`, `EXTRUDING`, `DRYING`, or `PACKAGING`, and whose
        `quality_disposition` is still `PENDING_QA` flips to `HELD`; second,
        for each run flipped in the first hop, its packaging job in `CREATED`
        or `LABEL_VERIFIED` becomes `BLOCKED`"

        Design: Difficulty/transitive_cascade/semolina_retest_reject_cascades_run_and_job
        """
        sc = setup_run_in_packaging(contract_code="C-REJ", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0)
        submit_lot_labs(sc["lot"]["id"], **WORSE_LABS)  # retest loops to QUARANTINED
        reject_lot(sc["lot"]["id"])

        lot = validate_success(api.get_semolina_lot(sc["lot"]["id"], PM))
        assert lot["status"] == "REJECTED"
        run = get_run(sc["run"]["id"])
        assert run["quality_disposition"] == "HELD", "hop 1"
        assert run["production_status"] == "PACKAGING", (
            "disposition cascade does not touch the production dimension"
        )
        job = get_packaging_job(sc["job"]["id"])
        assert job["status"] == "BLOCKED", "hop 2"

    def test_retest_loop_does_not_disturb_until_reject(self, api):
        """PRD: "submitting them against an `ACCEPTED` lot is the sanctioned
        retest loop — the lot falls back to `QUARANTINED`, its lab fields are
        overwritten, and its grade recomputed"
        PRD: "Retest alone does not disturb runs already referencing the lot;
        the cascade fires only on a subsequent reject."

        Design: Difficulty/transitive_cascade/semolina_retest_reject_cascades_run_and_job
        """
        sc = setup_run_in_packaging(contract_code="C-REJ2", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0)
        lot = submit_lot_labs(sc["lot"]["id"], **WORSE_LABS)
        assert lot["status"] == "QUARANTINED", "retest loop"
        assert get_run(sc["run"]["id"])["quality_disposition"] == "PENDING_QA"
        assert get_packaging_job(sc["job"]["id"])["status"] == "CREATED"

        reject_lot(sc["lot"]["id"])
        assert get_run(sc["run"]["id"])["quality_disposition"] == "HELD"
        assert get_packaging_job(sc["job"]["id"])["status"] == "BLOCKED"


class TestGlutenProductTestFailCascade:
    def _gf_completed_world(self, code):
        return setup_completed_run_with_goods_lot(
            contract_code=code,
            recipe_overrides={"recipe_name": "GF Fusilli", "gluten_free": True,
                              "shape_family": "SHORT_CUT"},
            gf_validated_line=True, die_shape_family="SHORT_CUT",
            planned_input_kg=500.0, actual_yield_kg=400.0,
        )

    def test_verified_fail_auto_rejects_run_and_created_lot(self, api):
        """PRD: "A verified product test with `FAIL` automatically moves the
        run's `quality_disposition` to `REJECTED`, cascading the run's
        finished-goods lots to `REJECTED` per §3.9."

        Design: Difficulty/transitive_cascade/gluten_product_test_fail_auto_rejects_run_and_lots
        """
        sc = self._gf_completed_world("C-GFT")
        test = record_and_verify_product_test(sc["run"]["id"], "FAIL")
        assert test["status"] == "VERIFIED"

        run = get_run(sc["run"]["id"])
        assert run["quality_disposition"] == "REJECTED", "hop 1, auto"
        goods = get_goods_lot(sc["goods_lot"]["id"])
        assert goods["status"] == "REJECTED", "hop 2"

    def test_verified_fail_frees_stored_lot_occupancy(self, api):
        """PRD: "Quality rejection — again from `PENDING_QA` or `HELD` — moves
        the disposition to `REJECTED` and writes off the run's finished-goods
        lots, moving any lot in `CREATED`, `STORED`, or `BLOCKED` to
        `REJECTED`; a lot that was occupying warehouse pallets stops occupying
        them."

        Design: Difficulty/transitive_cascade/gluten_product_test_fail_auto_rejects_run_and_lots
        """
        sc = self._gf_completed_world("C-GFT2")
        zone = create_zone("Z-GFT", "GLUTEN_FREE", 10)
        put_away(sc["goods_lot"]["id"], zone["id"])
        assert get_zone(zone["id"])["occupied_pallets"] == 1

        record_and_verify_product_test(sc["run"]["id"], "FAIL")
        goods = get_goods_lot(sc["goods_lot"]["id"])
        assert goods["status"] == "REJECTED"
        assert get_zone(zone["id"])["occupied_pallets"] == 0


class TestGoodsLotReleaseRequiresRunQualityReleased:
    def test_pending_qa_blocks_then_released_unlocks(self, api):
        """PRD: "the run's `quality_disposition` must be `RELEASED`
        (`ERR_RUN_QUALITY_NOT_RELEASED`)"
        PRD: "Release moves the lot to `RELEASED` and removes its pallets from
        the zone's occupancy."

        Design: Difficulty/cross_entity_state_dependency/goods_lot_release_requires_run_quality_released
        """
        sc = setup_stored_goods_lot(contract_code="C-XR", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0,
                                    zone_name="Z-XR", capacity_pallets=10)
        resp = api.release_goods_lot(sc["goods_lot"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_RUN_QUALITY_NOT_RELEASED)

        released = validate_success(api.quality_release_run(sc["run"]["id"], QAM))
        assert released["quality_disposition"] == "RELEASED"

        lot = release_goods_lot(sc["goods_lot"]["id"])
        assert lot["status"] == "RELEASED"

    def test_held_also_blocks_until_quality_release(self, api):
        """PRD: "the run's `quality_disposition` must be `RELEASED`
        (`ERR_RUN_QUALITY_NOT_RELEASED`)"
        PRD: "Quality release — from `PENDING_QA` or `HELD` — requires the
        run's `production_status` to be `COMPLETED` (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/goods_lot_release_requires_run_quality_released
        """
        sc = setup_stored_goods_lot(contract_code="C-XR2", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0,
                                    zone_name="Z-XR2", capacity_pallets=10)
        validate_success(api.quality_hold_run(sc["run"]["id"], QAM))
        assert get_run(sc["run"]["id"])["quality_disposition"] == "HELD"

        resp = api.release_goods_lot(sc["goods_lot"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_RUN_QUALITY_NOT_RELEASED)

        validate_success(api.quality_release_run(sc["run"]["id"], QAM))
        lot = release_goods_lot(sc["goods_lot"]["id"])
        assert lot["status"] == "RELEASED"


def test_gf_quality_release_requires_verified_product_test(api):
    """PRD: "Quality release — from `PENDING_QA` or `HELD` — requires the run's
    `production_status` to be `COMPLETED` (`ERR_INVALID_STATE`) and, for a
    gluten-free run, a verified `PRODUCT_TEST` with `PASS` on record
    (`ERR_GLUTEN_TEST_REQUIRED`)."
    PRD: "Release moves the disposition to `RELEASED`"

    Design: Corner/errors/gf_quality_release_requires_verified_product_test
    """
    sc = setup_completed_run_with_goods_lot(
        contract_code="C-GFQ",
        recipe_overrides={"recipe_name": "GF GFQ", "gluten_free": True,
                          "shape_family": "SHORT_CUT"},
        gf_validated_line=True, die_shape_family="SHORT_CUT",
        planned_input_kg=300.0, actual_yield_kg=200.0,
    )
    resp = api.quality_release_run(sc["run"]["id"], QAM)
    validate_error(resp, ApiErrorId.ERR_GLUTEN_TEST_REQUIRED)

    record_and_verify_product_test(sc["run"]["id"], "PASS")
    mid = get_run(sc["run"]["id"])
    assert mid["quality_disposition"] == "PENDING_QA", (
        "a verified PASS alone does not release"
    )

    released = validate_success(api.quality_release_run(sc["run"]["id"], QAM))
    assert released["quality_disposition"] == "RELEASED"


def test_zone_minor_monitoring_then_clear(api):
    """PRD: "A verified `MINOR` moves a `CLEAR` zone to `MONITORING`; a
    verified `NONE` returns a `MONITORING` zone to `CLEAR`."

    Design: Corner/state_machines/zone_minor_monitoring_then_clear
    """
    zone = create_zone("Z-MON", "CONVENTIONAL", 5)
    assert zone["pest_posture"] == "CLEAR"

    record_and_verify_pest_inspection(zone["id"], "MINOR",
                                      notes="single bait station hit")
    assert get_zone(zone["id"])["pest_posture"] == "MONITORING"

    record_and_verify_pest_inspection(zone["id"], "NONE", notes="all clear")
    assert get_zone(zone["id"])["pest_posture"] == "CLEAR"


def test_pest_inspection_double_verify_rejected(api):
    """PRD: "moving the inspection from `RECORDED` to `VERIFIED` and stamping
    `verified_by_user_id` and `verified_at`"
    PRD: "then transition legality on the target resource as
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/pest_inspection_double_verify_rejected
    """
    zone = create_zone("Z-IDM", "CONVENTIONAL", 5)
    insp = record_pest_inspection(zone["id"], "MINOR")
    verify_pest_inspection(insp["id"])

    resp = api.verify_pest_inspection(insp["id"], QAM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_zone(zone["id"])["pest_posture"] == "MONITORING", (
        "no double application of the zone effect"
    )


def test_quarantine_lift_recency_gate(api):
    """PRD: "Lifting a quarantine is a `QAManager` action requiring a verified
    `NONE` inspection whose `verified_at` is strictly later than
    `quarantined_at` (`ERR_QUARANTINE_LIFT_BLOCKED`); success returns the zone
    to `CLEAR`, clears `quarantined_at`"

    Design: Corner/validations/quarantine_lift_recency_gate
    """
    zone = create_zone("Z-QRC", "CONVENTIONAL", 5)
    record_and_verify_pest_inspection(zone["id"], "NONE", notes="routine sweep")
    record_and_verify_pest_inspection(zone["id"], "CRITICAL", notes="infestation")
    assert get_zone(zone["id"])["pest_posture"] == "QUARANTINED"

    resp = api.lift_quarantine(zone["id"], QAM)
    validate_error(resp, ApiErrorId.ERR_QUARANTINE_LIFT_BLOCKED)

    set_clock("2026-08-02T00:00:00Z")
    record_and_verify_pest_inspection(zone["id"], "NONE", notes="post-cleanout sweep")
    lifted = validate_success(api.lift_quarantine(zone["id"], QAM))
    assert lifted["pest_posture"] == "CLEAR"
    assert lifted["quarantined_at"] is None


def test_immediate_visibility_of_writes_and_cascades(api):
    """PRD: "Rejection moves a `QUARANTINED` lot to `REJECTED` and fires a
    three-hop hold cascade, atomically"

    Design: Corner/consistency_model/immediate_visibility_of_writes_and_cascades
    """
    sc = setup_scheduled_run(contract_code="C-IMM2", planned_input_kg=50.0,
                             with_die=False)
    recipe = get_recipe(sc["recipe"]["id"])
    assert recipe["status"] == "APPROVED"
    assert recipe["recipe_name"] == "Penne"
    assert recipe["unit_weight_g"] == 500

    submit_lot_labs(sc["lot"]["id"], **WORSE_LABS)
    reject_lot(sc["lot"]["id"])

    run = get_run(sc["run"]["id"])
    assert run["quality_disposition"] == "HELD", (
        "cascade visible on the very next read after the reject response"
    )
