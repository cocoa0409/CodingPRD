"""Tests covering the lottery weighting formula (PRD §3.6): the provisional
vs final variant divergence on sibling enrollment state, the rounding-order
pin on the poverty-index term, and the in-boundary boost.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_district,
    create_school,
    create_boundary_rule,
    create_window,
    open_window,
    register_family,
    create_student,
    create_sibling_bond,
    create_application,
    submit_application,
    advance_window_to_lottery_run,
    get_application,
    api_client,
    make_guardian_headers,
    TEST_USERS,
)


# =====================================================================
# Difficulty rule 1 / instance 1 — provisional vs final lottery_weight
# diverge on sibling enrollment status
# =====================================================================

def test_weight_preview_provisional_uses_submitted_sibling_as_boost(api):
    """PRD §3.6: "In the provisional variant — invoked during the open window
    to give families a forward-looking preview — the sibling boost fires when
    a sibling bond exists and the linked sibling has at least one application
    against this school whose status is `SUBMITTED`, `ACCEPTED`, or `ENROLLED`."

    Two students in one family both submit applications for the same school
    while the window is OPEN; the new student has a sibling bond pointing at
    the sibling. The provisional preview must therefore add the 0.500 sibling
    boost on top of the 1.000 base (no boundary, no poverty, no flag).

    Design: Difficulty/dual_variant_calc/lottery_weight_provisional_vs_final_diverge_on_sibling_status
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DV1A", name="Central", poverty_index_pct=0.00)
    school = create_school(
        district["id"], code="S01A", name="Hill School",
        school_type="MAGNET", grade_min=0, grade_max=5, total_seats=1,
    )
    window = create_window(district["id"], cycle_label="2026-27-VPA")
    family = register_family(district["id"], guardian_email="vpa@x.com",
                             residence_zone_code="Z99", poverty_flag=False)
    sib_stu = create_student(family["id"], full_name="Sibling Student",
                             grade_for_cycle=3)
    new_stu = create_student(family["id"], full_name="Applying Student",
                             grade_for_cycle=1)
    # Sibling bond pointing at the older student already at this school.
    create_sibling_bond(family["id"], new_stu["id"], sib_stu["id"], school["id"])
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    # Sibling student submits first (so their status is SUBMITTED at preview time).
    sib_app = create_application(family["id"], window["id"], sib_stu["id"],
                                 school["id"], choice_rank=1)
    submit_application(family["id"], sib_app["id"])
    new_app = create_application(family["id"], window["id"], new_stu["id"],
                                 school["id"], choice_rank=1)
    submit_application(family["id"], new_app["id"])
    res = api.get_application_weight_preview(
        new_app["id"], make_guardian_headers(family["id"])
    )
    data = validate_success(res, 200)
    assert data["variant"] == "provisional", (
        f"weight-preview must return variant='provisional'; got {data['variant']!r}"
    )
    assert data["lottery_weight"] == 1.500, (
        f"Provisional weight = 1.000 base + 0.500 sibling boost; "
        f"got {data['lottery_weight']!r}"
    )


def test_lottery_run_final_weight_omits_sibling_boost_when_sibling_not_enrolled(api):
    """PRD §3.6: "In the final variant — invoked once at the lottery instant,
    with the system clock at `lottery_runs_at` as the cutoff — the sibling
    boost fires only when the linked sibling has at least one application
    against this school whose status is `ENROLLED`."

    Same scenario as the provisional test: a sibling whose application is at
    most SUBMITTED-then-ACCEPTED (never ENROLLED before lottery time) means
    the final variant must drop the 0.500 sibling boost — the persisted
    lottery_weight is the bare base 1.000.

    Design: Difficulty/dual_variant_calc/lottery_weight_provisional_vs_final_diverge_on_sibling_status
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DV1B", name="Central", poverty_index_pct=0.00)
    # total_seats=2 so both applications can be ACCEPTED; sibling never
    # reaches ENROLLED before lottery_runs_at (no offer is accepted in setup).
    school = create_school(district["id"], code="S01B", name="Hill",
                           school_type="MAGNET", grade_min=0, grade_max=5,
                           total_seats=2)
    window = create_window(district["id"], cycle_label="2026-27-VPB")
    family = register_family(district["id"], guardian_email="vpb@x.com",
                             residence_zone_code="Z99", poverty_flag=False)
    sib_stu = create_student(family["id"], full_name="Sibling Student",
                             grade_for_cycle=3)
    new_stu = create_student(family["id"], full_name="Applying Student",
                             grade_for_cycle=1)
    create_sibling_bond(family["id"], new_stu["id"], sib_stu["id"], school["id"])
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    sib_app = create_application(family["id"], window["id"], sib_stu["id"],
                                 school["id"], choice_rank=1)
    submit_application(family["id"], sib_app["id"])
    new_app = create_application(family["id"], window["id"], new_stu["id"],
                                 school["id"], choice_rank=2)
    submit_application(family["id"], new_app["id"])
    advance_window_to_lottery_run(window["id"])
    persisted = get_application(new_app["id"])
    assert persisted["lottery_weight"] == 1.000, (
        f"Final variant must drop sibling boost when sibling is not ENROLLED; "
        f"expected 1.000 base only, got {persisted['lottery_weight']!r}"
    )


# =====================================================================
# Difficulty rule 2 / instance 1 — rounding-order pin on poverty boost
# =====================================================================

def test_lottery_weight_pins_poverty_term_rounded_then_summed(api):
    """PRD §3.6: "A poverty-index boost is then computed as the family's
    residence-district `poverty_index_pct` divided by 100 and multiplied by
    0.400, then independently rounded half-up to three decimal places before
    being summed — this rounding pin matters: the poverty term is rounded
    once on its own to three decimals, the final sum is rounded once to three
    decimals, and no other intermediate rounding occurs."

    With district poverty_index_pct=33.33: raw poverty term = 33.33/100*0.400
    = 0.133320; rounded-to-three independently = 0.133. Summed with base 1.000
    and rounded-to-three on the final = 1.133. No sibling, no boundary, no
    flag. The reverse ordering (round-the-final-sum-then-add-unrounded-poverty)
    is prohibited by the PRD pin.

    Design: Difficulty/combinatorial_formula/lottery_weight_round_per_term_then_sum_mode_b
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DRP1", name="Poverty33",
                               poverty_index_pct=33.33)
    school = create_school(district["id"], code="SRP1", name="Combo",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-RP")
    family = register_family(district["id"], guardian_email="rp@x.com",
                             residence_zone_code="ZRP", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=7)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    persisted = get_application(app["id"])
    assert persisted["lottery_weight"] == 1.133, (
        f"Pin: round(0.13332,3)=0.133; sum 1.000 base + 0.133 = 1.133; "
        f"got {persisted['lottery_weight']!r}"
    )
    assert persisted["status"] == "ACCEPTED", (
        f"Lone application against 5 seats must be ACCEPTED; "
        f"got {persisted['status']!r}"
    )


def test_lottery_weight_poverty_max_term_at_full_pct_yields_one_point_four(api):
    """PRD §3.6: "The maximum achievable poverty-index boost is 0.400 (reached
    at a 100% catchment poverty rate)."

    Companion to the rounding-order test: at poverty_index_pct = 100, the
    poverty term must equal exactly 0.400, so the final weight (with no
    other boosts) must be 1.400.

    Design: Difficulty/combinatorial_formula/lottery_weight_round_per_term_then_sum_mode_b
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DRP2", name="Poverty100",
                               poverty_index_pct=100.00)
    school = create_school(district["id"], code="SRP2", name="Combo",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-RP2")
    family = register_family(district["id"], guardian_email="rp2@x.com",
                             residence_zone_code="ZRP2", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=7)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    persisted = get_application(app["id"])
    assert persisted["lottery_weight"] == 1.400, (
        f"Max poverty boost = 0.400; sum 1.000 + 0.400 = 1.400; "
        f"got {persisted['lottery_weight']!r}"
    )


# =====================================================================
# Corner / calculations — in-boundary 0.300 boost
# =====================================================================

def test_lottery_weight_in_boundary_boost_three_tenths(api):
    """PRD §3.6: "An in-boundary boost of 0.300 is added when a `BoundaryRule`
    row exists tying this application's school to the family's
    `residence_zone_code` with `is_in_boundary` true; otherwise the in-boundary
    boost is zero."

    With a single SUBMITTED app under district poverty=0%, no sibling, no
    family poverty flag, but a matching in-boundary rule on the school's
    zone, the final weight is 1.000 base + 0.300 boundary = 1.300.

    Design: Corner/calculations/lottery_weight_in_boundary_bumps_three_tenths
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DBN", name="Bn", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SBN", name="Bns",
                           school_type="NEIGHBORHOOD", grade_min=0, grade_max=12,
                           total_seats=5)
    create_boundary_rule(school["id"], "ZBN", is_in_boundary=True)
    window = create_window(district["id"], cycle_label="2026-27-BN")
    family = register_family(district["id"], guardian_email="bn@x.com",
                             residence_zone_code="ZBN", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=3)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    persisted = get_application(app["id"])
    assert persisted["lottery_weight"] == 1.300, (
        f"In-boundary boost = 0.300; sum 1.000 + 0.300 = 1.300; "
        f"got {persisted['lottery_weight']!r}"
    )
    assert persisted["status"] == "ACCEPTED"
