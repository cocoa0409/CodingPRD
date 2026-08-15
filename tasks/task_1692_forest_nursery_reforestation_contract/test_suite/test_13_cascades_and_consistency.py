"""CASCADE A (grade shortfall), the projected-vs-actual yield divergence, and
single-request visibility of transition side effects."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_seed_zone, create_seed_lot, create_crop_batch, sow_batch, lift_batch,
    grade_batch, setup_ready_world,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]


def _shortfall_world(api):
    """Order 19000 allocated against a SOWN batch (projected 19747); contract
    requiring 18060 marked READY_TO_PLANT on that coverage; batch lifted."""
    ctx = setup_ready_world(
        acres=40, trees_per_acre=430, contingency_pct=0.05,
        order_quantity=19000,
        grade=False, with_storage=False,
    )
    assert ctx["required_seedlings"] == 18060
    lift_batch(ctx["batch"]["id"], lifted_on="2027-03-10", lifted_count=21000)
    return ctx


def test_grade_shortfall_releases_newest_allocation(api):
    """PRD §3.2: "While that reserved total exceeds the freshly recorded
    `plantable_count`, the server releases the batch's most recently created
    `ACTIVE` allocation — strictly in descending order of creation time, with no
    secondary tie-break on the identifier — and repeats until the reserved total
    no longer exceeds the plantable count; each released allocation flips to
    `RELEASED`."

    Design: Difficulty/transitive_cascade/grade_shortfall_cascade_order_contract_demotion
    """
    ctx = _shortfall_world(api)
    grade_res = get_success_data(
        api.grade_crop_batch(ctx["batch"]["id"], {"plantable_count": 18500}, NM)
    )
    assert grade_res["status"] == "GRADED"
    assert grade_res["cull_count"] == 2500

    allocation = get_success_data(api.get_allocation(ctx["allocation"]["id"], CO))
    assert allocation["status"] == "RELEASED", (
        "reserved 19000 exceeds the graded 18500, so the allocation is released"
    )


def test_grade_shortfall_demotes_order_and_contract(api):
    """PRD §3.2: "Every release recomputes its order's `allocated_quantity`, and
    an order that was `ALLOCATED` demotes back to `CONFIRMED` the moment its
    recomputed allocation total falls below the ordered `quantity`. Each such
    order demotion re-evaluates every planting contract supplied by that order,
    and a contract sitting at `READY_TO_PLANT` drops to `BLOCKED`."

    Design: Difficulty/transitive_cascade/grade_shortfall_cascade_order_contract_demotion
    """
    ctx = _shortfall_world(api)
    get_success_data(api.grade_crop_batch(ctx["batch"]["id"], {"plantable_count": 18500}, NM))

    order = get_success_data(api.get_seedling_order(ctx["order"]["id"], CO))
    assert order["status"] == "CONFIRMED", (
        f"order must demote ALLOCATED -> CONFIRMED, got {order['status']}"
    )
    assert order["allocated_quantity"] == 0

    contract = get_success_data(api.get_planting_contract(ctx["contract"]["id"], CO))
    assert contract["status"] == "BLOCKED", (
        f"the READY_TO_PLANT contract must drop to BLOCKED, got {contract['status']}"
    )


def test_projected_plantable_floor_formula_at_sow(api):
    """PRD §3.2: "the server computes the batch's `projected_plantable`, the
    forward-looking estimate used for planning reads: the whole-number floor of
    `sown_grams` multiplied by the seeds-per-gram figure for the lot's species —
    88 for `DOUGLAS_FIR`, 55 for `LOBLOLLY_PINE`, and two-tenths of a seed per
    gram for `WHITE_OAK` — multiplied by the lot's current `germination_pct`,
    and finally multiplied by 0.88 to allow for the expected cull rate of twelve
    percent."

    Design: Difficulty/dual_variant_calc/projected_vs_actual_batch_yield_diverge
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)
    batch = create_crop_batch(lot["id"], lot["version"])
    sown = sow_batch(batch["id"], 300)
    assert sown["projected_plantable"] == 19747, (
        f"floor(300 * 88 * 0.85 * 0.88) = 19747, got {sown['projected_plantable']}"
    )
    assert sown["status"] == "SOWN"


def test_graded_actual_yield_diverges_from_projection(api):
    """PRD §3.2: "The estimate deliberately ignores field reality and almost
    always differs from the physical count that grading later records." and
    "Grading then moves the batch from `LIFTED` to `GRADED`, recording the
    `plantable_count` of grade-acceptable seedlings, which must be positive and
    no greater than `lifted_count`; the server sets the batch's `cull_count` to
    the difference between `lifted_count` and `plantable_count`."

    Design: Difficulty/dual_variant_calc/projected_vs_actual_batch_yield_diverge
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)
    batch = create_crop_batch(lot["id"], lot["version"])
    sown = sow_batch(batch["id"], 300)
    projected = sown["projected_plantable"]

    lift_batch(batch["id"], lifted_on="2027-03-10", lifted_count=21000)
    graded = grade_batch(batch["id"], 20000)

    assert graded["plantable_count"] == 20000
    assert graded["cull_count"] == 1000, (
        f"cull_count = 21000 - 20000 = 1000, got {graded['cull_count']}"
    )
    assert projected != graded["plantable_count"], (
        "the forward-looking projection and the physical grading count are two "
        "variants that legitimately disagree on identical inputs"
    )
    assert projected == 19747 and graded["plantable_count"] - projected == 253


def test_immediate_model_single_request_visibility(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." and PRD §3.2: "Grading then moves the batch from `LIFTED` to
    `GRADED`, recording the `plantable_count` of grade-acceptable seedlings,
    which must be positive and no greater than `lifted_count`; the server sets
    the batch's `cull_count` to the difference between `lifted_count` and
    `plantable_count`."

    Design: Corner/consistency_model/immediate_model_single_request_visibility
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)
    batch = create_crop_batch(lot["id"], lot["version"])
    sow_batch(batch["id"], 300)
    lift_batch(batch["id"], lifted_on="2027-03-10", lifted_count=21000)

    res = api.grade_crop_batch(batch["id"], {"plantable_count": 20000}, NM)
    graded = validate_success(res, 200)
    assert graded["plantable_count"] == 20000
    assert graded["cull_count"] == 1000
    assert graded["status"] == "GRADED", (
        "the grade transition's own response carries the full updated batch"
    )
