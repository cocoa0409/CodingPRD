"""
Combinatorial formulas of the Urology Procedure Suite contract.

Two calculations here are combinatorial rather than linear. The occupancy window
reads six inputs spread across a procedure type, a room and a patient, applies
two independent additive branches to the in-room duration, and passes the room's
allowance through a multiplier, a floor and a scope surcharge in a pinned order —
so one shared configuration lands three cases on three different block ends. The
consignment billing total is combinatorial in its *sequence* rather than its
inputs: two lots holding identical unit counts at an identical unit price bill
different amounts, because each contributing line is rounded before the lines are
summed.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories
from test_helpers import fixtures
from test_helpers.assertions import assert_fields, assert_lot_counters
from test_helpers.constants import (
    ALLERGY_NONE,
    BILLING_PROVISIONAL,
    BILLING_STATUS_CONSIGNED,
    CASE_DRAFT,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    ROOM_TYPE_CYSTO_SUITE,
    ROOM_TYPE_URODYNAMICS_LAB,
    TYPE_CYSTOSCOPY,
    TYPE_PROSTATE_BIOPSY,
    TYPE_URODYNAMICS,
)

BIOPSY_NEEDLE_SKU = "BX-NEEDLE-18G"


# ─── Local setup helpers ───────────────────────────────────────────────────
def _register_patient(api, roster, **kwargs):
    """Register a patient as the practice's scheduler."""
    response = api.create_patient(
        factories.patient_payload(
            primary_urologist_id=roster.urologist["id"], **kwargs
        ),
        roster.scheduler_headers,
    )
    return get_success_data(response, 201)


def _draft(api, roster, patient, procedure_type, room, scheduled_start_at):
    """Draft one case and return the created row. A draft occupies nothing."""
    response = api.create_procedure_case(
        factories.procedure_case_payload(
            patient_id=patient["id"],
            procedure_type_id=procedure_type["id"],
            room_id=room["id"],
            primary_provider_id=roster.urologist["id"],
            scheduled_start_at=scheduled_start_at,
        ),
        roster.scheduler_headers,
    )
    return validate_success(response, 201)


def _setup_occupancy_stage(api, roster):
    """
    One shared configuration for the three-way occupancy comparison: two rooms
    with different baseline turnovers, three procedure types with different
    cleanup classes and scope obligations, and two patients whose renal function
    and anticoagulation differ.
    """
    cysto_room = fixtures.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    uds_room = fixtures.create_room(
        api,
        ROOM_TYPE_URODYNAMICS_LAB,
        name="Uro Lab",
        turnover_minutes=8,
        accreditation_body="AIUM",
        accreditation_expires_on="2027-01-31",
    )
    cysto_type = fixtures.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=True,
        requires_antibiotic=True,
        required_prep_codes=[],
    )
    uds_type = fixtures.create_procedure_type(
        api,
        TYPE_URODYNAMICS,
        base_minutes=45,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_URODYNAMICS_LAB,
        requires_scope=False,
        requires_antibiotic=False,
        required_prep_codes=[],
    )
    biopsy_type = fixtures.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=True,
        requires_antibiotic=True,
        required_prep_codes=[],
    )
    patient_normal_renal = _register_patient(
        api,
        roster,
        mrn="MRN-4201",
        full_name="Ivan Cole",
        date_of_birth="1962-04-11",
        egfr=60,
        anticoagulant_flag=False,
        antibiotic_allergy_class=ALLERGY_NONE,
    )
    patient_anticoagulated = _register_patient(
        api,
        roster,
        mrn="MRN-4202",
        full_name="Otto Blaine",
        date_of_birth="1949-07-30",
        egfr=40,
        anticoagulant_flag=True,
        antibiotic_allergy_class=ALLERGY_NONE,
    )
    return {
        "cysto_room": cysto_room,
        "uds_room": uds_room,
        "cysto_type": cysto_type,
        "uds_type": uds_type,
        "biopsy_type": biopsy_type,
        "patient_normal_renal": patient_normal_renal,
        "patient_anticoagulated": patient_anticoagulated,
    }


def _setup_two_lots_and_four_biopsy_drafts(api, roster):
    """
    Two ten-unit lots of the same stock-keeping unit at the same unit price, and
    four drafted biopsy cases — three that will each hold one unit of lot A and
    one that will hold three units of lot B.
    """
    room = fixtures.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    biopsy_type = fixtures.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=False,
        consignment_required=True,
        single_use_device_sku=BIOPSY_NEEDLE_SKU,
        required_prep_codes=[],
    )
    patient = _register_patient(
        api,
        roster,
        mrn="MRN-4203",
        full_name="Rosa Vance",
        date_of_birth="1958-02-02",
        egfr=60,
    )
    lot_a = fixtures.create_lot(
        api,
        supplier_name="Meridian Devices",
        sku=BIOPSY_NEEDLE_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=10,
        unit_price_cents=1999,
        lot_expires_on="2027-06-30",
    )
    lot_b = fixtures.create_lot(
        api,
        supplier_name="Anselm Surgical",
        sku=BIOPSY_NEEDLE_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=10,
        unit_price_cents=1999,
        lot_expires_on="2027-06-30",
    )

    fixtures.set_clock(api, "2026-09-14T07:00:00Z")
    starts = [
        "2026-09-14T08:00:00.000Z",
        "2026-09-14T09:00:00.000Z",
        "2026-09-14T10:00:00.000Z",
        "2026-09-14T11:00:00.000Z",
    ]
    cases = [
        _draft(api, roster, patient, biopsy_type, room, start) for start in starts
    ]
    return {
        "lot_a": lot_a,
        "lot_b": lot_b,
        "lot_a_cases": cases[:3],
        "lot_b_case": cases[3],
    }


# ─── The occupancy window across three entities ────────────────────────────
def test_cystoscopy_window_takes_no_duration_addition_and_a_doubled_scope_turnover(
    api, roster
):
    """PRD §3.2: "A quarter of an hour is added when the patient's
    `anticoagulant_flag` is true **and** the procedure type's `code` is
    `PROSTATE_BIOPSY` — anticoagulated prostate biopsies bleed and take longer to
    achieve haemostasis; the same patient having a cystoscopy gets no such
    addition."
    PRD §3.2: "First the room's own `turnover_minutes` is multiplied by a cleanup
    multiplier of 2 when the procedure type's `cleanup_class` is `HIGH` and by 1
    when it is `LOW`."
    PRD §3.2: "Only then, if the procedure type's `requires_scope` is true, a
    further twenty minutes is added for scope handling."
    PRD §3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by
    `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at`
    advanced by `turnover_minutes` minutes."

    Design: Difficulty/combinatorial_formula/cf_occupancy_window_three_way
    """
    stage = _setup_occupancy_stage(api, roster)

    case = _draft(
        api,
        roster,
        stage["patient_normal_renal"],
        stage["cysto_type"],
        stage["cysto_room"],
        "2026-09-14T14:00:00.000Z",
    )

    assert_fields(
        case,
        schedule_status=CASE_DRAFT,
        procedure_minutes=20,
        turnover_minutes=40,
        scheduled_end_at="2026-09-14T14:20:00.000Z",
        block_end_at="2026-09-14T15:00:00.000Z",
    )
    assert case["procedure_minutes"] == 20, (
        "a cystoscopy for a patient who is not anticoagulated and whose egfr is "
        "60 takes neither addition, so procedure_minutes stays at the type's 20 "
        f"base minutes, got {case['procedure_minutes']}"
    )
    assert case["turnover_minutes"] == 40, (
        "HIGH cleanup doubles the room's 10 baseline minutes to 20, the 15-minute "
        "floor does not bite, and the scope surcharge adds 20, expected 40, got "
        f"{case['turnover_minutes']}"
    )


def test_urodynamics_turnover_is_decided_by_the_quarter_hour_floor_not_the_room(
    api, roster
):
    """PRD §3.2: "That product is then floored at a quarter of an hour: whichever
    of the product and 15 minutes is larger becomes the working figure."
    PRD §3.2: "The floor applies to the multiplied product, not to the final
    figure — a `LOW`-cleanup scope procedure in a room with a baseline of 8
    minutes therefore ends up with 15 plus 20, that is 35 minutes of turnover,
    not 28."
    PRD §3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by
    `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at`
    advanced by `turnover_minutes` minutes."

    Design: Difficulty/combinatorial_formula/cf_occupancy_window_three_way
    """
    stage = _setup_occupancy_stage(api, roster)

    case = _draft(
        api,
        roster,
        stage["patient_normal_renal"],
        stage["uds_type"],
        stage["uds_room"],
        "2026-09-16T10:00:00.000Z",
    )

    assert_fields(
        case,
        schedule_status=CASE_DRAFT,
        procedure_minutes=45,
        turnover_minutes=15,
        scheduled_end_at="2026-09-16T10:45:00.000Z",
        block_end_at="2026-09-16T11:00:00.000Z",
    )
    assert case["turnover_minutes"] == 15, (
        "LOW cleanup leaves the room's 8 baseline minutes untouched, so the "
        "quarter-hour floor dominates and no scope surcharge applies, expected "
        f"15, got {case['turnover_minutes']}"
    )


def test_anticoagulated_low_egfr_biopsy_takes_both_duration_additions(api, roster):
    """PRD §3.2: "A quarter of an hour is added when the patient's
    `anticoagulant_flag` is true **and** the procedure type's `code` is
    `PROSTATE_BIOPSY` — anticoagulated prostate biopsies bleed and take longer to
    achieve haemostasis; the same patient having a cystoscopy gets no such
    addition."
    PRD §3.2: "Ten further minutes are added when the patient's `egfr` is
    strictly below 45 **and** the procedure type's `requires_antibiotic` is true,
    covering the extra time renal-dosed prophylaxis takes to run in."
    PRD §3.2: "The sum of `base_minutes` and those two additions is stored as the
    case's `procedure_minutes`."

    Design: Difficulty/combinatorial_formula/cf_occupancy_window_three_way
    """
    stage = _setup_occupancy_stage(api, roster)

    case = _draft(
        api,
        roster,
        stage["patient_anticoagulated"],
        stage["biopsy_type"],
        stage["cysto_room"],
        "2026-09-15T09:00:00.000Z",
    )

    assert_fields(
        case,
        schedule_status=CASE_DRAFT,
        procedure_minutes=55,
        turnover_minutes=40,
        scheduled_end_at="2026-09-15T09:55:00.000Z",
        block_end_at="2026-09-15T10:35:00.000Z",
    )
    assert case["procedure_minutes"] == 55, (
        "an anticoagulated prostate biopsy for a patient whose egfr is 40 takes "
        "the 30 base minutes plus 15 for anticoagulation plus 10 for renal-dosed "
        f"prophylaxis, expected 55, got {case['procedure_minutes']}"
    )


def test_one_configuration_lands_three_cases_on_three_different_block_ends(
    api, roster
):
    """PRD §3.2: "The arithmetic — call it the **occupancy window** — reads
    exactly three rows resolved from the case's own references at the moment of
    the mutation: one procedure type, one room and one patient."
    PRD §3.2: "The in-room duration starts from the procedure type's
    `base_minutes` and takes at most two additions."
    PRD §3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by
    `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at`
    advanced by `turnover_minutes` minutes."

    Design: Difficulty/combinatorial_formula/cf_occupancy_window_three_way
    """
    stage = _setup_occupancy_stage(api, roster)

    cysto_case = _draft(
        api,
        roster,
        stage["patient_normal_renal"],
        stage["cysto_type"],
        stage["cysto_room"],
        "2026-09-14T14:00:00.000Z",
    )
    uds_case = _draft(
        api,
        roster,
        stage["patient_normal_renal"],
        stage["uds_type"],
        stage["uds_room"],
        "2026-09-16T10:00:00.000Z",
    )
    biopsy_case = _draft(
        api,
        roster,
        stage["patient_anticoagulated"],
        stage["biopsy_type"],
        stage["cysto_room"],
        "2026-09-15T09:00:00.000Z",
    )

    assert_fields(
        cysto_case,
        procedure_minutes=20,
        turnover_minutes=40,
        scheduled_end_at="2026-09-14T14:20:00.000Z",
        block_end_at="2026-09-14T15:00:00.000Z",
    )
    assert_fields(
        uds_case,
        procedure_minutes=45,
        turnover_minutes=15,
        scheduled_end_at="2026-09-16T10:45:00.000Z",
        block_end_at="2026-09-16T11:00:00.000Z",
    )
    assert_fields(
        biopsy_case,
        procedure_minutes=55,
        turnover_minutes=40,
        scheduled_end_at="2026-09-15T09:55:00.000Z",
        block_end_at="2026-09-15T10:35:00.000Z",
    )

    triples = [
        (case["procedure_minutes"], case["turnover_minutes"])
        for case in (cysto_case, uds_case, biopsy_case)
    ]
    assert triples == [(20, 40), (45, 15), (55, 40)], (
        "the three cases drafted from one shared configuration must land on "
        f"three distinct duration pairs, got {triples}"
    )


# ─── Rounding order: per line first, then sum ──────────────────────────────
def test_three_one_unit_lines_are_each_rounded_before_they_are_summed(api, roster):
    """PRD §2.7: "Where a total is assembled from several contributions, the order
    of rounding is pinned and is part of the contract: each contributing line is
    rounded to whole cents first, and the rounded line values are then summed."
    PRD §3.6: "A *line* is one procedure case holding units of that lot, and the
    lines are enumerated in ascending `created_at` order — the order does not
    change the sum but is pinned so that the sequence of per-line roundings is
    reproducible."
    PRD §3.6: "Rounding once at the end, over the summed raw products, is not the
    rule and produces a different figure: with a `unit_price_cents` of 1999, a
    markup factor of 1.185 and three reserved lines of one unit each, the pinned
    per-line-then-sum order gives 2369 cents a line and 7107 cents in total,
    whereas summing first would give 7106 cents."

    Design: Difficulty/combinatorial_formula/cf_billing_round_per_line_then_sum
    """
    scene = _setup_two_lots_and_four_biopsy_drafts(api, roster)

    for case in scene["lot_a_cases"]:
        fixtures.reserve_device(api, roster, case["id"], scene["lot_a"], quantity=1)

    lot_a = validate_success(
        api.get_consignment_lot(scene["lot_a"]["id"], roster.admin_headers)
    )

    assert_fields(
        lot_a,
        unit_price_cents=1999,
        billed_amount_cents=7107,
        billing_basis=BILLING_PROVISIONAL,
        billing_status=BILLING_STATUS_CONSIGNED,
    )
    assert lot_a["billed_amount_cents"] == 7107, (
        "three one-unit lines at 1999 cents under the provisional 1.185 factor "
        "each round to 2369 cents, so the lot bills 7107 cents; summing the raw "
        f"products first would give 7106, got {lot_a['billed_amount_cents']}"
    )
    assert_lot_counters(
        lot_a, available=7, reserved=3, consumed=0, returned=0, wasted=0
    )


def test_one_three_unit_line_is_rounded_exactly_once(api, roster):
    """PRD §3.6: "Each line's value is the lot's `unit_price_cents` multiplied by
    the applicable factor, multiplied by that case's `device_quantity`, and then
    **rounded half up to a whole number of cents**."
    PRD §3.6: "`billed_amount_cents` is the sum of those already-rounded line
    values."
    PRD §3.6: "Its factor is 1 plus the 18.5% consignment markup, so 1.185, and
    it sums only the lines whose `device_state` is `RESERVED`."

    Design: Difficulty/combinatorial_formula/cf_billing_round_per_line_then_sum
    """
    scene = _setup_two_lots_and_four_biopsy_drafts(api, roster)

    fixtures.reserve_device(
        api, roster, scene["lot_b_case"]["id"], scene["lot_b"], quantity=3
    )

    lot_b = validate_success(
        api.get_consignment_lot(scene["lot_b"]["id"], roster.admin_headers)
    )

    assert_fields(
        lot_b,
        unit_price_cents=1999,
        billed_amount_cents=7106,
        billing_basis=BILLING_PROVISIONAL,
        billing_status=BILLING_STATUS_CONSIGNED,
    )
    assert lot_b["billed_amount_cents"] == 7106, (
        "a single line of three units at 1999 cents under the provisional 1.185 "
        "factor is rounded exactly once, expected 7106 cents, got "
        f"{lot_b['billed_amount_cents']}"
    )
    assert_lot_counters(
        lot_b, available=7, reserved=3, consumed=0, returned=0, wasted=0
    )


def test_identical_unit_counts_bill_one_cent_apart_across_the_two_line_shapes(
    api, roster
):
    """PRD §2.7: "Summing raw products and rounding once at the end is explicitly
    not the rule and produces different totals; §3.5 works the divergence through
    with concrete numbers."
    PRD §3.6: "Rounding once at the end, over the summed raw products, is not the
    rule and produces a different figure: with a `unit_price_cents` of 1999, a
    markup factor of 1.185 and three reserved lines of one unit each, the pinned
    per-line-then-sum order gives 2369 cents a line and 7107 cents in total,
    whereas summing first would give 7106 cents."
    PRD §3.6: "The one-cent gap is the observable signature of the pinned order,
    and the pinned order is the one this service implements."

    Design: Difficulty/combinatorial_formula/cf_billing_round_per_line_then_sum
    """
    scene = _setup_two_lots_and_four_biopsy_drafts(api, roster)

    for case in scene["lot_a_cases"]:
        fixtures.reserve_device(api, roster, case["id"], scene["lot_a"], quantity=1)
    fixtures.reserve_device(
        api, roster, scene["lot_b_case"]["id"], scene["lot_b"], quantity=3
    )

    lot_a = validate_success(
        api.get_consignment_lot(scene["lot_a"]["id"], roster.admin_headers)
    )
    lot_b = validate_success(
        api.get_consignment_lot(scene["lot_b"]["id"], roster.admin_headers)
    )

    assert lot_a["unit_price_cents"] == lot_b["unit_price_cents"] == 1999, (
        "both lots must carry the same unit price for the comparison to isolate "
        f"the rounding order, got {lot_a['unit_price_cents']} and "
        f"{lot_b['unit_price_cents']}"
    )
    assert lot_a["quantity_reserved"] == lot_b["quantity_reserved"] == 3, (
        "both lots must hold the same number of reserved units, got "
        f"{lot_a['quantity_reserved']} and {lot_b['quantity_reserved']}"
    )
    assert lot_a["billed_amount_cents"] == 7107, (
        "the three-line lot bills 7107 cents, got "
        f"{lot_a['billed_amount_cents']}"
    )
    assert lot_b["billed_amount_cents"] == 7106, (
        "the one-line lot bills 7106 cents, got "
        f"{lot_b['billed_amount_cents']}"
    )
    gap = lot_a["billed_amount_cents"] - lot_b["billed_amount_cents"]
    assert gap == 1, (
        "the observable signature of the pinned per-line-then-sum order is a "
        f"one-cent gap between the two line shapes, got {gap}"
    )
