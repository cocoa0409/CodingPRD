"""Acceptance sampling plans, capacity verdicts and lot disposition."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import (
    assert_close,
    assert_lot_counters,
    assert_sampling_plan,
)
from test_helpers.factories import disposition_payload, sampling_plan_payload
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import validate_error


def test_sample_size_floor_binds_for_a_lot_of_four_and_the_first_draw_moves_the_lot(
    world: World,
):
    """A four-battery lot draws three samples with an acceptance number of zero.

    "The result is then clamped from both ends to lie between 3 and 12 inclusive -- the floor
    and the ceiling both genuinely bind, so a lot of 4 batteries still draws 3 samples". The
    tier table then reads "0 when the size is 4 or fewer", and the first draw "requires the lot
    to be in `ASSEMBLY` and moves it `ASSEMBLY -> LOT_TESTING`".

    Design: Difficulty/combinatorial_formula/lot_sampling_plan_sqrt_offset_clamp_tier_mode_a
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-SMALL", 4)
    world.certify_assembly(lot["id"], "ASM-SMALL-1")

    plan = world.draw_plan(lot["id"], "initial plan")
    assert_sampling_plan(plan, sample_size=3, acceptance_number=0, revision=1)

    stored = world.read_lot(lot["id"])
    assert_sampling_plan(stored, sample_size=3, acceptance_number=0, revision=1)
    assert stored["process_state"] == C.LOT_TESTING


def test_lithium_offset_is_absorbed_by_the_ceiling_while_lead_stays_at_ten(world: World):
    """The same quantity of 100 draws 12 samples in lithium and 10 in lead-acid.

    "Lithium chemistry adds a fixed offset of 2 to that base, because lithium acceptance
    sampling is tightened by regulation; lead-acid adds nothing." A base of 10 becomes 12 for
    lithium, which the ceiling of 12 exactly absorbs, and both sizes are above 8 so both read an
    acceptance number of 2.

    Design: Difficulty/combinatorial_formula/lot_sampling_plan_sqrt_offset_clamp_tier_mode_a
    """
    lithium_design = world.approved_lithium_design("CD-LI-900")
    li_lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-LI", 100, design_id=lithium_design)
    world.certify_assembly(li_lot["id"], "ASM-LI-1")
    li_plan = world.draw_plan(li_lot["id"], "initial plan")
    assert_sampling_plan(li_plan, sample_size=12, acceptance_number=2, revision=1)

    pb_lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-BIG", 100)
    world.certify_assembly(pb_lot["id"], "ASM-BIG-1")
    pb_plan = world.draw_plan(pb_lot["id"], "initial plan")
    assert_sampling_plan(pb_plan, sample_size=10, acceptance_number=2, revision=1)


def test_retest_redraws_the_plan_under_the_tightened_branch(world: World):
    """A retest doubles the sample size, decrements the acceptance number and redraws in place.

    "It increments `retest_count`, zeroes `completed_test_count`, `failed_test_count` and
    `passed_cycle_life_count` so that the tightened plan is judged on fresh evidence, and then
    **immediately redraws the plan itself** under the tightened branch, incrementing
    `sampling_plan_revision` by 1". For a lead-acid lot of 100 the clamped size of 10 becomes
    min(20, 20) and the tier value of 2 becomes 1.

    Design: Difficulty/combinatorial_formula/lot_sampling_plan_sqrt_offset_clamp_tier_mode_a
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-BIG", 100)
    world.certify_assembly(lot["id"], "ASM-BIG-1")
    world.draw_plan(lot["id"], "initial plan")

    world.disposition(lot["id"], C.DISPOSITION_QUARANTINE, note="operator hold")
    retested = world.disposition(lot["id"], C.DISPOSITION_RETEST, note="resample tightened")

    assert retested["process_state"] == C.LOT_TESTING
    assert_lot_counters(
        retested, completed=0, failed=0, passed_cycle_life=0, retest_count=1
    )
    assert_sampling_plan(retested, sample_size=20, acceptance_number=1, revision=2)

    redrawn = world.draw_plan(lot["id"], "tightened retest plan")
    assert_sampling_plan(redrawn, sample_size=20, acceptance_number=1, revision=3)


def test_a_redraw_with_the_pre_retest_lot_version_is_refused_as_stale(world: World):
    """The version captured before the retest no longer matches the lot.

    "A `QualityInspector` draws the lot's acceptance sampling plan, optionally recording a
    `plan_reason`, and must supply `expected_lot_version` matching the lot's current `version`
    as described in section 2.6." The retest itself bumped the version, so the stale value is
    refused and the plan revision does not move.

    Design: Difficulty/combinatorial_formula/lot_sampling_plan_sqrt_offset_clamp_tier_mode_a
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-BIG", 100)
    world.certify_assembly(lot["id"], "ASM-BIG-1")
    world.draw_plan(lot["id"], "initial plan")
    world.disposition(lot["id"], C.DISPOSITION_QUARANTINE, note="operator hold")
    stale_version = world.read_lot(lot["id"])["version"]
    world.disposition(lot["id"], C.DISPOSITION_RETEST, note="resample tightened")

    refused = world.api.draw_sampling_plan(
        lot["id"], sampling_plan_payload(stale_version, plan_reason="stale redraw"), world.qa_a
    )
    validate_error(refused, E.ERR_STALE_LOT_VERSION)
    assert_sampling_plan(world.read_lot(lot["id"]), revision=2)


def test_capacity_reading_on_the_rounded_threshold_passes(testing_world: World):
    """441.8 Ah is exactly the one-decimal threshold for a 465.0 Ah design and passes.

    "it is a `PASS` when the measured capacity is greater than or equal to the pinned
    `nominal_capacity_ah` multiplied by 0.95 and **rounded to one decimal place before the
    comparison**, and a `FAIL` otherwise; a reading exactly equal to that rounded threshold
    passes." 465.0 * 0.95 is 441.75, which rounds to 441.8, and the yield of
    441.8 / 465.0 * 100 rounds half up to 95.01.

    Design: Difficulty/boundary_precision_check/capacity_pass_threshold_is_the_rounded_value_not_the_exact_one
    """
    world = testing_world
    test = world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T08:00:00Z",
        "2026-09-03T10:00:00Z",
        draw_kw=5.00,
    )
    world.set_clock("2026-09-03T10:00:00Z")
    recorded = world.record_capacity(test["id"], 441.8)

    assert recorded["result"] == C.CAPACITY_RESULT_PASS
    assert_close(recorded["yield_pct"], 95.01, "yield_pct", 2)
    assert recorded["test_state"] == C.TEST_STATE_COMPLETED

    lot = world.read_lot(world.lot_id)
    assert_lot_counters(lot, completed=1, failed=0, passed_cycle_life=0)
    assert lot["process_state"] == C.LOT_TESTING
    assert_close(lot["lot_capacity_yield_pct"], 95.01, "lot_capacity_yield_pct", 2)


def test_capacity_reading_one_tenth_below_the_rounded_threshold_fails(testing_world: World):
    """441.7 Ah misses the rounded threshold by a tenth and fails without quarantining the lot.

    "When the incremented `failed_test_count` becomes strictly greater than the lot's
    `acceptance_number`, the lot moves `LOT_TESTING -> QUARANTINED` inside the same request".
    A single failure against an acceptance number of 2 leaves the lot in `LOT_TESTING`, the
    yield is still stamped on the failed test as 94.99, and the lot-level yield stays null
    because its window holds no passing test.

    Design: Difficulty/boundary_precision_check/capacity_pass_threshold_is_the_rounded_value_not_the_exact_one
    """
    world = testing_world
    test = world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T08:00:00Z",
        "2026-09-03T10:00:00Z",
        draw_kw=5.00,
    )
    world.set_clock("2026-09-03T10:00:00Z")
    recorded = world.record_capacity(test["id"], 441.7)

    assert recorded["result"] == C.CAPACITY_RESULT_FAIL
    assert_close(recorded["yield_pct"], 94.99, "yield_pct", 2)

    lot = world.read_lot(world.lot_id)
    assert_lot_counters(lot, completed=1, failed=1, passed_cycle_life=0)
    assert lot["process_state"] == C.LOT_TESTING
    assert lot["lot_capacity_yield_pct"] is None


def test_two_quarantine_retest_passes_tighten_once_and_reset_the_evidence(world: World):
    """The lot re-enters LOT_TESTING twice, and the tightening branch is a flag, not a ramp.

    "It increments `retest_count`, zeroes `completed_test_count`, `failed_test_count` and
    `passed_cycle_life_count` so that the tightened plan is judged on fresh evidence". A lot of
    50 draws 8 samples with an acceptance number of 1, and every retest thereafter draws
    min(16, 20) samples with an acceptance number of max(0, 0), so the second pass tightens no
    further than the first.

    Design: Difficulty/non_linear_state_machine/production_lot_quarantine_retest_cycle_with_hard_cap
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-0050", 50)
    world.certify_assembly(lot["id"], "ASM-0050-1")

    first_plan = world.draw_plan(lot["id"])
    assert_sampling_plan(first_plan, sample_size=8, acceptance_number=1, revision=1)
    assert world.read_lot(lot["id"])["process_state"] == C.LOT_TESTING

    quarantined = world.disposition(lot["id"], C.DISPOSITION_QUARANTINE, note="visual defect")
    assert quarantined["process_state"] == C.LOT_QUARANTINED

    first_retest = world.disposition(lot["id"], C.DISPOSITION_RETEST, note="first retest")
    assert first_retest["process_state"] == C.LOT_TESTING
    assert_lot_counters(first_retest, completed=0, failed=0, passed_cycle_life=0, retest_count=1)
    assert_sampling_plan(first_retest, sample_size=16, acceptance_number=0, revision=2)

    world.disposition(lot["id"], C.DISPOSITION_QUARANTINE, note="second defect")
    second_retest = world.disposition(lot["id"], C.DISPOSITION_RETEST, note="second retest")
    assert second_retest["process_state"] == C.LOT_TESTING
    assert_lot_counters(second_retest, retest_count=2)
    assert_sampling_plan(second_retest, sample_size=16, acceptance_number=0, revision=3)


def test_the_third_quarantine_is_a_trap_whose_only_exit_is_scrap(world: World):
    """At two retests the QUARANTINED exit closes and only scrapping remains.

    "It requires the lot to be `QUARANTINED` with a clear hold and `retest_count` strictly less
    than 2; a third attempt is `ERR_RETEST_LIMIT_REACHED`." Release is unreachable from
    `QUARANTINED`, scrapping "is terminal. Every assembly of the lot is set to `REJECTED` and
    every `SCHEDULED` test on those assemblies is `VOIDED`", and a second scrap is refused.

    Design: Difficulty/non_linear_state_machine/production_lot_quarantine_retest_cycle_with_hard_cap
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-0050", 50)
    assembly = world.certify_assembly(lot["id"], "ASM-0050-1")
    world.draw_plan(lot["id"])
    for note in ("visual defect", "second defect"):
        world.disposition(lot["id"], C.DISPOSITION_QUARANTINE, note=note)
        world.disposition(lot["id"], C.DISPOSITION_RETEST, note="retest " + note)
    world.disposition(lot["id"], C.DISPOSITION_QUARANTINE, note="third defect")

    validate_error(
        world.api.disposition_lot(
            lot["id"], disposition_payload(C.DISPOSITION_RETEST, "third retest attempt"),
            world.qa_a,
        ),
        E.ERR_RETEST_LIMIT_REACHED,
    )
    validate_error(
        world.api.disposition_lot(
            lot["id"],
            disposition_payload(C.DISPOSITION_RELEASE, "attempt to escape quarantine"),
            world.qa_a,
        ),
        E.ERR_LOT_STATE_INVALID,
    )

    scrapped = world.disposition(lot["id"], C.DISPOSITION_SCRAP, note="unsalvageable")
    assert scrapped["process_state"] == C.LOT_SCRAPPED
    assert world.read_assembly(assembly["id"])["certification_status"] == C.CERT_REJECTED

    validate_error(
        world.api.disposition_lot(
            lot["id"], disposition_payload(C.DISPOSITION_SCRAP, "repeat scrap"), world.qa_a
        ),
        E.ERR_LOT_STATE_INVALID,
    )
    final = world.read_lot(lot["id"])
    assert_lot_counters(final, retest_count=2)
    assert_sampling_plan(final, revision=3)


def test_one_failed_result_quarantines_the_lot_revokes_both_assemblies_and_voids_the_sibling_test(
    world: World,
):
    """A single FAIL fans out to an assembly and a test the trigger never named.

    "Hop three, because the lot became `QUARANTINED`, moves every `BatteryAssembly` of that lot
    whose `certification_status` is `CERTIFIED` to `REVOKED`. Hop four, because those assemblies
    were revoked, moves every `CapacityTest` on them whose `test_state` is `SCHEDULED` to
    `VOIDED`, which releases that test's share of its chamber's power draw." A lot of 4 draws a
    3 / 0 plan, so the first failure already exceeds the acceptance number.

    Design: Difficulty/transitive_cascade/cascade_b_failed_capacity_test_quarantines_lot_revokes_assemblies_voids_tests
    """
    chamber_id = world.add_chamber()
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-0004", 4)
    asm_a = world.certify_assembly(lot["id"], "ASM-A")
    asm_b = world.certify_assembly(lot["id"], "ASM-B")
    assert asm_a["certification_status"] == C.CERT_CERTIFIED
    assert asm_b["certification_status"] == C.CERT_CERTIFIED

    plan = world.draw_plan(lot["id"])
    assert_sampling_plan(plan, sample_size=3, acceptance_number=0)

    test_a = world.schedule_test(
        asm_a["id"], chamber_id, "2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z", draw_kw=4.00
    )
    test_b = world.schedule_test(
        asm_b["id"], chamber_id, "2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z", draw_kw=4.00
    )
    world.set_clock("2026-09-03T10:00:00Z")

    recorded = world.record_capacity(test_a["id"], 441.7)
    assert recorded["result"] == C.CAPACITY_RESULT_FAIL
    assert_close(recorded["yield_pct"], 94.99, "yield_pct", 2)

    lot_after = world.read_lot(lot["id"])
    assert_lot_counters(lot_after, completed=1, failed=1)
    assert lot_after["process_state"] == C.LOT_QUARANTINED
    assert lot_after["lot_capacity_yield_pct"] is None
    assert lot_after["last_test_recorded_by_worker_id"] == world.qa_a_id

    assert world.read_assembly(asm_a["id"])["certification_status"] == C.CERT_REVOKED
    assert world.read_assembly(asm_b["id"])["certification_status"] == C.CERT_REVOKED
    assert world.read_assembly(asm_a["id"])["rework_count"] == 0

    voided = world.read_test(test_b["id"])
    assert voided["test_state"] == C.TEST_STATE_VOIDED
    assert voided["result"] is None
    assert world.read_test(test_a["id"])["test_state"] == C.TEST_STATE_COMPLETED


def test_a_failure_that_stays_within_the_acceptance_number_starts_no_cascade(
    testing_world: World,
):
    """Only a breach of the acceptance number quarantines; one failure of ten does not.

    "If that increment pushes `failed_test_count` strictly above the lot's `acceptance_number`,
    hop two moves the lot's `process_state` from `LOT_TESTING` to `QUARANTINED`." A lot of 100
    carries an acceptance number of 2, so one failure leaves the lot testing, the assembly
    certified and any sibling test still scheduled.

    Design: Difficulty/transitive_cascade/cascade_b_failed_capacity_test_quarantines_lot_revokes_assemblies_voids_tests
    """
    world = testing_world
    failing = world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T08:00:00Z",
        "2026-09-03T10:00:00Z",
        draw_kw=4.00,
    )
    sibling = world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T12:00:00Z",
        "2026-09-03T14:00:00Z",
        draw_kw=4.00,
    )
    world.set_clock("2026-09-03T10:00:00Z")
    world.record_capacity(failing["id"], 441.7)

    lot = world.read_lot(world.lot_id)
    assert_lot_counters(lot, completed=1, failed=1)
    assert lot["process_state"] == C.LOT_TESTING
    assert world.read_assembly(world.assembly_id)["certification_status"] == C.CERT_CERTIFIED
    assert world.read_test(sibling["id"])["test_state"] == C.TEST_STATE_SCHEDULED
