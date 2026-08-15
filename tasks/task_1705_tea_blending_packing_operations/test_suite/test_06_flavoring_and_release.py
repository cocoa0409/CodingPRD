"""Flavoring application gates, the flavored-recipe QC fork, the batch
release moisture gate, and the state-beats-safety priority pair.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    apply_flavoring,
    create_active_recipe,
    create_blended_batch,
    create_flavoring,
    create_qc_batch,
    create_released_lot,
    create_supplier,
    get_batch,
    release_batch,
    setup_single_lot_scenario,
    single_component,
    submit_qc,
    validate_error,
    validate_paginated,
    validate_success,
)

BM = TEST_USERS["blend_master_headers"]
QA = TEST_USERS["qa_manager_headers"]


def _blended_flavored_batch(flavoring_overrides=None, certification_target="CONVENTIONAL"):
    """Supplier + RELEASED GREEN lot + flavored recipe (95% leaf, 5%
    flavoring) + batch target 20.0 walked to BLENDED."""
    return setup_single_lot_scenario(
        leaf_type="GREEN", lot_weight_kg=30.0, target_weight_kg=20.0,
        allocated_kg=19.0, pack_format="TEA_BAG",
        certification_target=certification_target, advance_to="BLENDED",
        flavoring_spec=dict({"name": "Jasmine", "allergen_tags": [],
                             "natural_certified": True,
                             "cost_per_kg_cents": 2500, "pct": 5.0},
                            **(flavoring_overrides or {})))


def test_flavored_batch_submit_qc_requires_flavoring(api):
    """PRD §3.5: "An unflavored batch enters from `BLENDED` — but if the
    recipe names a flavoring, submitting straight from `BLENDED` is
    rejected with `ERR_FLAVORING_REQUIRED`, because the flavoring must be
    applied first."
    PRD §3.5: "A flavored batch enters from `FLAVORED`, and exactly one
    flavoring application must exist for it."

    Design: Corner/state_machines/flavored_batch_submit_qc_requires_flavoring
    """
    ctx = _blended_flavored_batch()
    batch = ctx["batch"]
    assert batch["status"] == "BLENDED"

    res = api.submit_qc(batch["id"], BM)
    validate_error(res, ApiErrorId.ERR_FLAVORING_REQUIRED)

    application = apply_flavoring(batch["id"], ctx["flavoring"]["id"],
                                  batch["flavoring_kg"])
    assert application["batch_id"] == batch["id"]
    submitted = submit_qc(batch["id"])
    assert submitted["status"] == "QC_REVIEW"


def test_flavoring_dose_mismatch_rejected(api):
    """PRD §3.5: "The `applied_kg` must equal the batch's computed
    `flavoring_kg` exactly at three-decimal precision, else
    `ERR_FLAVORING_DOSE_MISMATCH`."

    flavoring_kg is exactly 1.0 (20.0 kg x 5%); applying 1.2 fails.

    Design: Corner/validations/flavoring_dose_mismatch_rejected
    """
    ctx = _blended_flavored_batch(
        {"name": "Mint", "cost_per_kg_cents": 2000})
    batch = ctx["batch"]
    assert batch["flavoring_kg"] == 1.0

    res = api.apply_flavoring(
        batch["id"],
        {"flavoring_id": ctx["flavoring"]["id"], "applied_kg": 1.2}, BM)
    validate_error(res, ApiErrorId.ERR_FLAVORING_DOSE_MISMATCH)
    assert get_batch(batch["id"])["status"] == "BLENDED"
    _, meta = validate_paginated(
        api.list_batch_flavoring_applications(batch["id"], BM))
    assert meta["total_count"] == 0


def test_flavoring_mismatch_rejected(api):
    """PRD §3.5: "The request's `flavoring_id` must equal the recipe's own
    flavoring reference, else `ERR_FLAVORING_MISMATCH`."

    A different ACTIVE flavoring at the correct dose is still rejected:
    recipe identity is locked, not just quantity.

    Design: Corner/validations/flavoring_mismatch_rejected
    """
    ctx = _blended_flavored_batch(
        {"name": "Cardamom", "cost_per_kg_cents": 2200})
    other = create_flavoring(name="Ginger", allergen_tags=[],
                             natural_certified=True, cost_per_kg_cents=1800)
    batch = ctx["batch"]

    res = api.apply_flavoring(
        batch["id"],
        {"flavoring_id": other["id"], "applied_kg": batch["flavoring_kg"]},
        BM)
    validate_error(res, ApiErrorId.ERR_FLAVORING_MISMATCH)
    assert get_batch(batch["id"])["status"] == "BLENDED"


def test_synthetic_flavoring_on_organic_rejected(api):
    """PRD §3.5: "And when the recipe's `certification_target` is
    `ORGANIC`, only a flavoring whose `natural_certified` flag is true
    may be applied — a synthetic agent on an organic batch is rejected
    with `ERR_SYNTHETIC_ON_ORGANIC`."

    Design: Corner/validations/synthetic_flavoring_on_organic_rejected
    """
    ctx = _blended_flavored_batch(
        {"name": "Synth Vanilla", "natural_certified": False,
         "cost_per_kg_cents": 1500},
        certification_target="ORGANIC")
    batch = ctx["batch"]

    res = api.apply_flavoring(
        batch["id"],
        {"flavoring_id": ctx["flavoring"]["id"], "applied_kg": 1.0}, BM)
    validate_error(res, ApiErrorId.ERR_SYNTHETIC_ON_ORGANIC)
    assert get_batch(batch["id"])["status"] == "BLENDED"


def test_retired_flavoring_rejected(api):
    """PRD §3.5: "The flavoring must still be `ACTIVE`, else
    `ERR_FLAVORING_NOT_ACTIVE`."
    PRD §3.3: "Retiring one moves it to `RETIRED` — a terminal state —
    which leaves existing flavoring applications untouched but bars all
    future use: recipe activation or flavoring application referencing a
    retired flavoring fails with `ERR_FLAVORING_NOT_ACTIVE`."

    The flavoring is retired after its recipe was activated, so only the
    application-time referential check can catch it.

    Design: Corner/validations/retired_flavoring_rejected
    """
    ctx = _blended_flavored_batch(
        {"name": "Rose", "cost_per_kg_cents": 2000})
    batch = ctx["batch"]

    retired = validate_success(
        api.retire_flavoring(ctx["flavoring"]["id"], BM), 200)
    assert retired["status"] == "RETIRED"

    res = api.apply_flavoring(
        batch["id"],
        {"flavoring_id": ctx["flavoring"]["id"], "applied_kg": 1.0}, BM)
    validate_error(res, ApiErrorId.ERR_FLAVORING_NOT_ACTIVE)
    assert get_batch(batch["id"])["status"] == "BLENDED"


def test_moisture_release_gate_boundary(api):
    """PRD §3.5: "Its `measured_moisture_pct` must be at most 7.0
    percent, else `ERR_MOISTURE_OUT_OF_RANGE`."

    A batch blended at exactly 7.0 releases (inclusive); its twin at 7.1
    fails and stays in QC_REVIEW.

    Design: Corner/calculations/moisture_release_gate_boundary
    """
    supplier = create_supplier(name="Moist Co")
    lot1 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-01", weight_kg=30.0)
    lot2 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-02", weight_kg=30.0)
    recipe = create_active_recipe(
        name="RMO", pack_format="LOOSE_PACK",
        components=[single_component("GREEN", "C", 100.0)])
    batch_a = create_qc_batch(recipe, 20.0, [(lot1["id"], 20.0)],
                              measured_moisture_pct=7.0)
    batch_b = create_qc_batch(recipe, 20.0, [(lot2["id"], 20.0)],
                              measured_moisture_pct=7.1)

    released_a = release_batch(batch_a["id"])
    assert released_a["status"] == "RELEASED", "7.0 is at most 7.0"

    res = api.release_batch(batch_b["id"], QA)
    validate_error(res, ApiErrorId.ERR_MOISTURE_OUT_OF_RANGE)
    assert get_batch(batch_b["id"])["status"] == "QC_REVIEW"


class TestStateBeatsSafetyPriority:
    def _held_organic_batch_with_synthetic_flavoring(self, api):
        """ORGANIC flavored batch in BLENDED, cascaded to ON_HOLD by
        recalling its lot; the recipe's flavoring is synthetic, so
        apply-flavoring violates both the state gate and the safety
        gate."""
        supplier = create_supplier(name="Priority Co",
                                   origin_region="Nilgiri")
        lot = create_released_lot(supplier["id"], leaf_type="GREEN",
                                  weight_kg=30.0, aroma_score=90,
                                  briskness_score=88, appearance_score=92)
        flavoring = create_flavoring(name="Nut Crunch",
                                     allergen_tags=["TREE_NUT"],
                                     natural_certified=False,
                                     cost_per_kg_cents=2500)
        recipe = create_active_recipe(
            name="R9", certification_target="ORGANIC", pack_format="TEA_BAG",
            components=[single_component("GREEN", "C", 95.0)],
            flavoring_id=flavoring["id"], flavoring_pct=5.0)
        batch = create_blended_batch(recipe["id"], 20.0, [(lot["id"], 19.0)],
                                     measured_moisture_pct=6.0)
        validate_success(api.recall_lot(lot["id"], QA), 200)
        assert get_batch(batch["id"])["status"] == "ON_HOLD"
        return batch, flavoring

    def test_held_batch_flavoring_returns_state_error(self, api):
        """PRD §2.10: "Every request is checked against the following
        sequence, and the first failure encountered wins — later checks
        never mask an earlier rejection"
        PRD §2.10: "6. Endpoint state preconditions: the specific state
        the endpoint demands, reported with the endpoint-specific code
        where one exists — `ERR_LOT_NOT_RELEASABLE`,
        `ERR_SUPPLIER_SUSPENDED`, `ERR_LOT_NOT_RELEASED`,
        `ERR_RECIPE_NOT_ACTIVE`, `ERR_BATCH_NOT_RELEASABLE`,
        `ERR_BATCH_NOT_FLAVORABLE`, `ERR_FLAVORING_REQUIRED`,
        `ERR_LINE_NOT_ACTIVE`, `ERR_CONTRACT_NOT_ACTIVE`, or
        `ERR_RUN_OUTSIDE_WINDOW` — and otherwise with the generic
        `ERR_INVALID_STATE`."
        PRD §2.10: "8. Business safety gates — the moisture limits, the
        organic-flavoring rule, and certification presence and volume —
        reported as `ERR_MOISTURE_OUT_OF_RANGE`,
        `ERR_SYNTHETIC_ON_ORGANIC`, `ERR_CERT_NOT_ACTIVE`, or
        `ERR_CERT_VOLUME_EXHAUSTED`."

        One request that is both not-BLENDED (state) and synthetic-on-
        ORGANIC (safety) must surface the state error.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_held_batch_flavoring
        """
        batch, flavoring = (
            self._held_organic_batch_with_synthetic_flavoring(api))
        res = api.apply_flavoring(
            batch["id"],
            {"flavoring_id": flavoring["id"], "applied_kg": 1.0}, BM)
        validate_error(res, ApiErrorId.ERR_BATCH_NOT_FLAVORABLE)

    def test_rejected_application_has_no_side_effects(self, api):
        """PRD §3.5: "A successful application persists a flavoring
        application stamped with `applied_by_user_id`, books
        `flavoring_cost_cents` as the applied kilograms multiplied by
        the flavoring's `cost_per_kg_cents` rounded half-up to whole
        cents, copies the flavoring's `allergen_tags` onto the batch,
        and moves the batch to `FLAVORED`."

        The state-rejected request persists no application and leaves
        the batch ON_HOLD with an empty allergen list.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_held_batch_flavoring
        """
        batch, flavoring = (
            self._held_organic_batch_with_synthetic_flavoring(api))
        res = api.apply_flavoring(
            batch["id"],
            {"flavoring_id": flavoring["id"], "applied_kg": 1.0}, BM)
        validate_error(res, ApiErrorId.ERR_BATCH_NOT_FLAVORABLE)

        _, meta = validate_paginated(
            api.list_batch_flavoring_applications(batch["id"], BM))
        assert meta["total_count"] == 0, "no FlavoringApplication created"
        after = get_batch(batch["id"])
        assert after["status"] == "ON_HOLD"
        assert after["allergen_tags"] == []
