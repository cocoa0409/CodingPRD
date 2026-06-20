"""Case cost & payment calculations: estimated vs actual cost, over-run banding,
ASC payment grouping, office-based floor, and day utilization.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: calculations section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
ORMGR = TEST_USERS["or_manager_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc / estimated_vs_actual_case_cost_diverge
# ===========================================================================
def test_estimated_cost_at_booking_mac_60min():
    """PRD §3.9: "The labor part is the procedure's `scheduled_minutes` multiplied
    by the OR minute rate of 1,200 cents per scheduled minute (twelve dollars a minute)."
    PRD §3.9: "The anesthesia part is a flat base keyed to the procedure's
    `anesthesia_class`: zero cents for `LOCAL`, 18,000 cents for `MAC`, 32,000 cents
    for `REGIONAL`, and 55,000 cents for `GENERAL`."

    A booked MAC 60-min case: 60*1200 + 18000 = 90000.

    Design: Difficulty/dual_variant_calc/estimated_vs_actual_case_cost_diverge
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        assign_anesthesia=True, assign_recovery=True,
        world_kwargs={"with_clock": "2026-07-01T00:00:00.000Z"})
    assert case["estimated_cost_cents"] == 90000, (
        f"Expected estimate 90000, got {case['estimated_cost_cents']}")


def test_actual_cost_diverges_from_estimate_with_overrun():
    """PRD §3.12: "The labor part is the case's `actual_minutes` multiplied by the same
    OR minute rate of 1,200 cents per minute."
    PRD §3.12: "Because the actual variant uses recorded minutes and consumed quantities
    and adds the over-run penalty, it diverges from the estimate whenever `actual_minutes`
    differs from `scheduled_minutes` or `consumed_qty` differs from `planned_qty`."

    actual 78 vs sched 60 -> 18 over -> band1 15*800=12000 + band2 3*1500=4500 = 16500;
    actual = 78*1200 + 18000 + 16500 = 128100, which differs from the 90000 estimate.

    Design: Difficulty/dual_variant_calc/estimated_vs_actual_case_cost_diverge
    """
    world, block, case, _ = fixtures.setup_case_in_recovery(
        actual_world_clock="2026-07-01T00:00:00.000Z",
        start_min=480, block_start=480, block_end=600)
    resp = api_client.complete_case(case["id"], {"actual_minutes": 78}, ORMGR)
    data = validate_success(resp, 200)
    assert data["estimated_cost_cents"] == 90000, data["estimated_cost_cents"]
    assert data["actual_cost_cents"] == 128100, data["actual_cost_cents"]
    assert data["estimated_cost_cents"] != data["actual_cost_cents"]


# ===========================================================================
# Difficulty / combinatorial_formula / overrun_tiered_penalty_marginal_banding
# ===========================================================================
def test_overrun_penalty_three_band_marginal():
    """PRD §3.12: "The penalty is then charged by **marginal banding** across three bands,
    each minute charged at its own band's rate rather than at a single blended rate."
    PRD §3.12: "The first band covers over-run minutes 1 through 15 at 800 cents per minute.
    The second band covers over-run minutes 16 through 45 — that is, the minutes above 15
    up to a cumulative 45 — at 1,500 cents per minute. The third band covers every over-run
    minute beyond 45 at 3,000 cents per minute."

    actual 106 vs sched 60 -> 46 over -> 15*800 + 30*1500 + 1*3000 = 60000 penalty;
    actual = 106*1200 + 18000 + 60000 = 205200.

    Design: Difficulty/combinatorial_formula/overrun_tiered_penalty_marginal_banding
    """
    world, block, case, _ = fixtures.setup_case_in_recovery(
        actual_world_clock="2026-07-01T00:00:00.000Z",
        start_min=480, block_start=480, block_end=720)
    resp = api_client.complete_case(case["id"], {"actual_minutes": 106}, ORMGR)
    data = validate_success(resp, 200)
    assert data["actual_cost_cents"] == 205200, data["actual_cost_cents"]


def test_overrun_penalty_boundary_exactly_15_min():
    """PRD §3.12: "The first band covers over-run minutes 1 through 15 at 800 cents per minute."
    PRD §3.12: "The boundaries are exact: minute 15 falls in band one, and minute 16 begins band two."

    actual 75 vs sched 60 = exactly 15 over -> band1 only 15*800 = 12000;
    actual = 75*1200 + 18000 + 12000 = 120000.

    Design: Difficulty/combinatorial_formula/overrun_tiered_penalty_marginal_banding
    """
    world, block, case, _ = fixtures.setup_case_in_recovery(
        actual_world_clock="2026-07-01T00:00:00.000Z",
        start_min=480, block_start=480, block_end=720)
    resp = api_client.complete_case(case["id"], {"actual_minutes": 75}, ORMGR)
    data = validate_success(resp, 200)
    assert data["actual_cost_cents"] == 120000, data["actual_cost_cents"]


# ===========================================================================
# Difficulty / combinatorial_formula / asc_payment_grouping_pinned_evaluation_order
# ===========================================================================
def _setup_device_intensive_second_case():
    """Two cases for the SAME patient on the SAME day; first completed, second has a
    device implant consumed_qty 2 and is then completed. Returns the second case dict
    after completion (turnover 0 so cases can sit adjacent)."""
    world = fixtures.setup_facility_world(
        turnover_minutes=0, with_clock="2026-07-01T00:00:00.000Z",
        with_bay=True, with_anesthesia=True)
    fac, room, surg, pat, day = (world["facility"], world["room"], world["surgeon"],
                                 world["patient"], world["day"])
    anes, bay = world["anesthesiologist"], world["bay"]
    proc1 = fixtures.create_procedure(fac["id"], cpt_code="11111", description="First proc",
                                      scheduled_minutes=30, cms_payment_indicator="COVERED_ASC",
                                      cms_base_rate_cents=100000, anesthesia_class="MAC")
    proc2 = fixtures.create_procedure(fac["id"], cpt_code="22222", description="Device proc",
                                      scheduled_minutes=30, cms_payment_indicator="DEVICE_INTENSIVE",
                                      cms_base_rate_cents=200000, anesthesia_class="MAC",
                                      device_offset_pct=30)
    item = fixtures.create_supply_item(fac["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=12345, is_device=True, on_hand_qty=10)
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 600)
    case1 = fixtures.book_case(block["id"], block["version"], pat["id"], proc1["id"], 480,
                               anesthesiologist_id=anes["id"], recovery_bay_id=bay["id"])
    v1 = fixtures.block_version(block["id"])
    case2 = fixtures.book_case(block["id"], v1, pat["id"], proc2["id"], 510,
                               anesthesiologist_id=anes["id"], recovery_bay_id=bay["id"])
    imp = fixtures.attach_implant(case2["id"], item["id"], 2)
    get_success_data(api_client.patch_implant(imp["id"], {"consumed_qty": 2}, ORMGR))
    for c in (case1, case2):
        fixtures.record_check(c["id"], "HP_REVIEW", "PASS")
        fixtures.clear_case(c["id"], "2026-07-10T00:00:00.000Z")
    get_success_data(api_client.lock_day(day["id"], SCHED))
    # Complete case1 first so case2 is the 2nd same-patient/day completed case.
    for c in (case1, case2):
        get_success_data(api_client.start_case(c["id"], ORMGR))
        get_success_data(api_client.case_to_recovery(c["id"], ORMGR))
    fixtures.complete_case(case1["id"], 30)
    return case2["id"]


def test_payment_grouping_device_offset_then_multi_proc_reduction():
    """PRD §3.13: "The applied device offset is the **lesser** of that percentage offset
    and the actual summed device cost, and the grouped amount is the base plus that device offset."
    PRD §3.13: "if this completing case is the second or later non-cancelled completed case
    for the **same patient on the same `service_date`** — where ordering among the patient's
    same-day completed cases is by `start_min` ascending and then `created_at` ascending —
    the grouped amount (already including any device offset from step two) is reduced by 50
    percent, that is, multiplied by one-half and rounded half-up to a whole cent; the first
    such case for the patient that day takes no reduction."

    DEVICE_INTENSIVE base 200000, offset_pct 30, device consumed 2*12345=24690;
    offset = min(round(200000*0.30)=60000, 24690) = 24690 -> grouped 224690;
    2nd same-patient/day case -> reduction: round(224690*0.5) = 112345.

    Design: Difficulty/combinatorial_formula/asc_payment_grouping_pinned_evaluation_order
    """
    case2_id = _setup_device_intensive_second_case()
    resp = api_client.complete_case(case2_id, {"actual_minutes": 30}, ORMGR)
    data = validate_success(resp, 200)
    assert data["cms_payment_cents"] == 112345, data["cms_payment_cents"]


def test_payment_grouping_device_offset_uses_lesser_of_pct_and_actual():
    """PRD §3.13: "Then compute a percentage offset as the base multiplied by the procedure's
    `device_offset_pct` divided by 100, rounded half-up to a whole cent. The applied device
    offset is the **lesser** of that percentage offset and the actual summed device cost, and
    the grouped amount is the base plus that device offset."

    Same scenario: the percentage offset (60000) exceeds the actual device cost (24690), so
    the lesser (24690) is applied, then the 2nd-case 50% reduction -> 112345 (not 130000,
    which the 60000 percentage offset path would have produced before reduction).

    Design: Difficulty/combinatorial_formula/asc_payment_grouping_pinned_evaluation_order
    """
    case2_id = _setup_device_intensive_second_case()
    resp = api_client.complete_case(case2_id, {"actual_minutes": 30}, ORMGR)
    data = validate_success(resp, 200)
    assert data["cms_payment_cents"] == 112345, data["cms_payment_cents"]


# ===========================================================================
# Corner / calculations / estimated_cost_with_addon_surcharge
# ===========================================================================
def test_estimate_includes_addon_surcharge():
    """PRD §3.9: "The fourth part is an add-on surcharge of 40,000 cents (four hundred
    dollars), added only when the case's `is_add_on` is true and zero otherwise."
    PRD §3.9: "The anesthesia part is a flat base keyed to the procedure's
    `anesthesia_class`: zero cents for `LOCAL`, 18,000 cents for `MAC`, 32,000 cents
    for `REGIONAL`, and 55,000 cents for `GENERAL`."

    Add-on GENERAL 60-min, no implants: 60*1200 + 55000 + 40000 = 167000.

    Design: Corner/calculations/estimated_cost_with_addon_surcharge
    """
    world = fixtures.setup_facility_world(proc_overrides={"anesthesia_class": "GENERAL"})
    fac, room, surg, day = world["facility"], world["room"], world["surgeon"], world["day"]
    proc, pat1 = world["procedure"], world["patient"]
    pat2 = fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 720)
    fixtures.book_case(block["id"], block["version"], pat1["id"], proc["id"], 480)
    get_success_data(api_client.lock_day(day["id"], SCHED))
    v1 = fixtures.block_version(block["id"])
    resp = api_client.book_case(block["id"], {
        "expected_block_version": v1, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 600, "is_add_on": True}, SCHED)
    data = validate_success(resp, 201)
    assert data["estimated_cost_cents"] == 167000, data["estimated_cost_cents"]
    assert data["is_add_on"] is True


# ===========================================================================
# Corner / calculations / overrun_tier_boundary_exactly_15_min
#   (distinct corner instance; same boundary value, separate Design tag)
# ===========================================================================
def test_overrun_cost_at_exactly_15_min_boundary():
    """PRD §3.12: "The first band covers over-run minutes 1 through 15 at 800 cents per minute."
    PRD §3.12: "The case's `actual_cost_cents` is the sum of the labor part, the anesthesia
    part, the per-line-rounded consumed-implant total, the add-on surcharge, and this
    over-run penalty."

    actual 75, sched 60 -> 15 over (band1 only) -> 75*1200 + 18000 + 12000 = 120000.

    Design: Corner/calculations/overrun_tier_boundary_exactly_15_min
    """
    world, block, case, _ = fixtures.setup_case_in_recovery(
        actual_world_clock="2026-07-01T00:00:00.000Z",
        start_min=480, block_start=480, block_end=720)
    resp = api_client.complete_case(case["id"], {"actual_minutes": 75}, ORMGR)
    data = validate_success(resp, 200)
    assert data["actual_cost_cents"] == 120000, data["actual_cost_cents"]


# ===========================================================================
# Corner / calculations / office_based_payment_floor_applied
# ===========================================================================
def test_office_based_floor_raises_below_floor_payment():
    """PRD §3.13: "Step four enforces an office-based floor: when the procedure's
    `cms_payment_indicator` is `OFFICE_BASED`, if the grouped amount is below 9,000 cents
    it is raised to that 9,000-cent floor."

    OFFICE_BASED base 5000 (< 9000 floor), first case for patient -> cms_payment_cents 9000.

    Design: Corner/calculations/office_based_payment_floor_applied
    """
    world, block, case, _ = fixtures.setup_case_in_recovery(
        actual_world_clock="2026-07-01T00:00:00.000Z",
        start_min=480, block_start=480, block_end=600,
        world_kwargs={"turnover_minutes": 0,
                      "proc_overrides": {"cpt_code": "29881", "description": "Office",
                                         "scheduled_minutes": 30,
                                         "cms_payment_indicator": "OFFICE_BASED",
                                         "cms_base_rate_cents": 5000,
                                         "anesthesia_class": "MAC"}})
    resp = api_client.complete_case(case["id"], {"actual_minutes": 30}, ORMGR)
    data = validate_success(resp, 200)
    assert data["cms_payment_cents"] == 9000, data["cms_payment_cents"]


# ===========================================================================
# Corner / calculations / day_utilization_computed_after_booking
# ===========================================================================
def test_day_utilization_after_single_booking():
    """PRD §3.14: "otherwise it is 100 times the used minutes divided by the prime-time
    capacity, rounded half-up to one decimal place."
    PRD §3.3: "A day exposes a computed `booked_minutes` (the sum of `scheduled_minutes`
    over its non-cancelled cases)..."

    One 60-min case, OR prime [420,960)=540 capacity -> 100*60/540 = 11.1; booked 60.

    Design: Corner/calculations/day_utilization_computed_after_booking
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        world_kwargs={"prime_time_start_min": 420, "prime_time_end_min": 960})
    day = get_success_data(api_client.get_surgical_day(world["day"]["id"], SCHED))
    assert day["utilization_pct"] == 11.1, day["utilization_pct"]
    assert day["booked_minutes"] == 60, day["booked_minutes"]
