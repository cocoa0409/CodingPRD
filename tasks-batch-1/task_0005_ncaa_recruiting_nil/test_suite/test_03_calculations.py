"""Calculation claims: NIL tier classification (banker's rounding +
boundary), slot utilization base vs projected variants, and the
program penalty-tier weighted scoring (PRD §2.10, §3.4, §3.5, §3.7).
"""
from test_helpers import (
    validate_success,
    create_program, create_student_athlete, setup_certified_athlete,
    setup_program_with_certified_athlete,
    create_draft_offer, send_offer,
    submit_certification,
    create_nil_deal,
    report_incident, open_investigation,
    report_and_sustain_incident,
    make_student_athlete_headers,
    create_nil_deal_payload,
    TEST_USERS,
)


# ─── Corner: NIL DE_MINIMIS boundary ────────────────────


def test_nil_deal_at_60000_cents_is_standard_just_below_is_de_minimis(api):
    """PRD §3.5: "If `net_value_cents` is strictly less than 60,000 cents
    (six hundred dollars), `tier` is `DE_MINIMIS`. Otherwise, if
    `net_value_cents` is strictly less than 500,000 cents (five thousand
    dollars), `tier` is `STANDARD`."
    PRD §3.5: "The boundary at exactly 60,000 cents and exactly 500,000
    cents therefore falls into the higher tier — exactly 60,000 cents is
    `STANDARD`, exactly 500,000 cents is `HIGH_VALUE`."

    Design: Corner/calculations/nil_de_minimis_boundary_just_below_cutoff
    """
    athlete = setup_certified_athlete(sport_code="BASEBALL")

    below = validate_success(api.create_nil_deal(
        create_nil_deal_payload(
            student_athlete_id=athlete["id"],
            brand_name="JustBelow",
            gross_value_cents=59999,
            agent_fee_pct=0.0,
        ),
        make_student_athlete_headers(athlete["id"]),
    ), 201)
    assert below["net_value_cents"] == 59999
    assert below["tier"] == "DE_MINIMIS"

    at_boundary = validate_success(api.create_nil_deal(
        create_nil_deal_payload(
            student_athlete_id=athlete["id"],
            brand_name="ExactBoundary",
            gross_value_cents=60000,
            agent_fee_pct=0.0,
        ),
        make_student_athlete_headers(athlete["id"]),
    ), 201)
    assert at_boundary["net_value_cents"] == 60000
    assert at_boundary["tier"] == "STANDARD"


# ─── Corner: zero-incident program stays at NONE ────────


def test_program_penalty_tier_none_when_no_sustained_incidents(api):
    """PRD §3.7: "The system then recomputes the program's `penalty_tier`
    by summing the `severity_weight` of every `BoosterIncident` for that
    `program_id` whose `status` is `SUSTAINED` (which now includes the
    one just sustained) — incidents in any other status, including
    `DISMISSED`, contribute nothing. If the total weight is exactly 0,
    the program's `penalty_tier` is `NONE`."

    Design: Corner/calculations/penalty_tier_zero_incidents_returns_none
    """
    program = create_program(sport_code="MBB", school_name="Clean U", scholarship_slot_cap=13)
    athlete = create_student_athlete(sport_code="MBB", full_name="Q")

    # Two incidents — one REPORTED, one INVESTIGATING. Neither is SUSTAINED.
    inc1 = report_incident(program, athlete, alleged_value_cents=100_000, booster_name="A")
    inc2 = report_incident(program, athlete, alleged_value_cents=200_000, booster_name="B")
    open_investigation(inc2["id"])

    prog = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert prog["penalty_tier"] == "NONE"


# ─── Difficulty: dual_variant_calc instances ────────────


def test_slot_utilization_projected_excludes_denied_athletes(api):
    """PRD §3.4: "The `projected` variant produces `slots_projected`: it
    counts every `ScholarshipOffer` whose `program_id` matches the
    program and whose `status` is `DRAFT`, `SENT`, or `ACCEPTED`,
    excluding those whose recipient athlete already has at least one
    `EligibilityCertification` with `status` `DENIED`."

    Design: Difficulty/dual_variant_calc/scholarship_slot_utilization_base_vs_projected_diverge
    """
    from test_helpers import deny_certification
    program = create_program(sport_code="FOOTBALL", school_name="Denied Project U",
                             scholarship_slot_cap=85)

    # Athlete A: CERTIFIED + SENT offer.
    athlete_a = setup_certified_athlete(sport_code="FOOTBALL", full_name="A1", gpa=3.500)
    offer_a = create_draft_offer(program["id"], athlete_a["id"], annual_value_cents=5_000_000)
    send_offer(offer_a["id"], program["version"])

    # Athlete B: PENDING cert that gets DENIED, plus a DRAFT offer.
    athlete_b = create_student_athlete(full_name="B1", sport_code="FOOTBALL", gpa=2.000)
    cert_b = submit_certification(athlete_b["id"])
    deny_certification(cert_b["id"], denial_reason="GPA_BELOW_MIN")
    # The denial cascade auto-WITHDRAWs any existing DRAFT offer for B;
    # so we create the DRAFT for B AFTER the denial — at this point B is
    # INELIGIBLE but a Coach can still create a DRAFT (PRD §3.4 says only
    # the SEND transition checks certification; DRAFT create has no
    # eligibility precondition).
    create_draft_offer(program["id"], athlete_b["id"], annual_value_cents=4_000_000)

    base = validate_success(api.get_program_utilization(
        program["id"], TEST_USERS["coach_headers"], params={"variant": "base"},
    ), 200)
    proj = validate_success(api.get_program_utilization(
        program["id"], TEST_USERS["coach_headers"], params={"variant": "projected"},
    ), 200)

    # base sees only SENT/ACCEPTED → A's offer only.
    assert base["slot_count"] == 1
    # projected EXCLUDES B (athlete has a DENIED cert), so still just A.
    assert proj["slot_count"] == 1


def test_slot_utilization_base_vs_projected_diverge_when_draft_pending(api):
    """PRD §3.4: "The `base` variant — which is the default if `variant`
    is omitted — produces `slots_committed`: it counts every
    `ScholarshipOffer` whose `program_id` matches the program and whose
    `status` is either `SENT` or `ACCEPTED`."
    PRD §3.4: "The `projected` variant produces `slots_projected`: it
    counts every `ScholarshipOffer` whose `program_id` matches the
    program and whose `status` is `DRAFT`, `SENT`, or `ACCEPTED`,
    excluding those whose recipient athlete already has at least one
    `EligibilityCertification` with `status` `DENIED`."

    Design: Difficulty/dual_variant_calc/scholarship_slot_utilization_base_vs_projected_diverge
    """
    program = create_program(sport_code="FOOTBALL", school_name="State U", scholarship_slot_cap=85)

    # Athlete A — CERTIFIED, SENT offer (counts in base AND projected)
    athlete_a = setup_certified_athlete(sport_code="FOOTBALL", full_name="Athlete A", gpa=3.500)
    offer_a = create_draft_offer(program["id"], athlete_a["id"], annual_value_cents=5_000_000)
    send_offer(offer_a["id"], program["version"])

    # Athlete B — certification still PENDING (no approve), DRAFT offer
    athlete_b = create_student_athlete(full_name="Athlete B", sport_code="FOOTBALL", gpa=3.200)
    submit_certification(athlete_b["id"])  # PENDING, not approved
    create_draft_offer(program["id"], athlete_b["id"], annual_value_cents=4_500_000)

    base_res = api.get_program_utilization(
        program["id"], TEST_USERS["coach_headers"],
        params={"variant": "base"},
    )
    base = validate_success(base_res, 200)
    assert base["variant"] == "base"
    assert base["slot_count"] == 1

    proj_res = api.get_program_utilization(
        program["id"], TEST_USERS["coach_headers"],
        params={"variant": "projected"},
    )
    proj = validate_success(proj_res, 200)
    assert proj["variant"] == "projected"
    assert proj["slot_count"] == 2

    assert base["slot_count"] != proj["slot_count"]


def test_nil_value_net_basis_yields_de_minimis_at_70000_gross_with_fee(api):
    """PRD §3.5: "first, `net_value_cents` is the gross value multiplied
    by one minus `agent_fee_pct`, with the resulting cent value rounded
    to the nearest whole cent using banker's rounding (half-to-even).
    Only then is the resulting integer cent count compared against the
    tier cutoffs"
    PRD §3.5: "If `net_value_cents` is strictly less than 60,000 cents
    (six hundred dollars), `tier` is `DE_MINIMIS`."

    Design: Difficulty/dual_variant_calc/nil_value_gross_vs_net_diverge_on_tier
    """
    # gross=70000, fee=0.20 → net = round_half_even(56000.0) = 56000 →
    # 56000 < 60000 → DE_MINIMIS. A naive gross-only classifier would
    # tier 70000 as STANDARD.
    athlete = setup_certified_athlete(sport_code="MBB", full_name="Net Basis")
    res = api.create_nil_deal(
        create_nil_deal_payload(
            student_athlete_id=athlete["id"],
            brand_name="FeeBrand",
            gross_value_cents=70000,
            agent_fee_pct=0.20,
        ),
        make_student_athlete_headers(athlete["id"]),
    )
    deal = validate_success(res, 201)
    assert deal["net_value_cents"] == 56000
    assert deal["tier"] == "DE_MINIMIS"


def test_nil_value_net_basis_yields_de_minimis_at_60000_gross_with_fee(api):
    """PRD §3.5: "The order of operations matters at the boundary: a deal
    with `gross_value_cents` 60,000 and `agent_fee_pct` 0.10 yields
    `net_value_cents` 54,000 — `DE_MINIMIS`, not `STANDARD` — whereas a
    naive classification on the gross alone would place it in `STANDARD`."

    Design: Difficulty/dual_variant_calc/nil_value_gross_vs_net_diverge_on_tier
    """
    athlete = setup_certified_athlete(sport_code="MBB", full_name="Athlete A")
    res = api.create_nil_deal(
        create_nil_deal_payload(
            student_athlete_id=athlete["id"],
            brand_name="Sneakers Inc",
            gross_value_cents=60000,
            agent_fee_pct=0.10,
        ),
        make_student_athlete_headers(athlete["id"]),
    )
    deal = validate_success(res, 201)
    assert deal["net_value_cents"] == 54000
    assert deal["tier"] == "DE_MINIMIS"


# ─── Difficulty: combinatorial_formula instances ────────


def test_program_penalty_tier_postseason_ban_at_total_15(api):
    """PRD §3.7: "one whose value is at least 2,500,000 receives 15"
    PRD §3.7: "Otherwise (a total of 15 or more), the tier is
    `POSTSEASON_BAN`. The boundaries at 5 and 15 fall into the higher
    tier."

    Design: Difficulty/combinatorial_formula/program_penalty_tier_three_input_nonlinear_aggregation
    """
    program = create_program(sport_code="FOOTBALL", school_name="BAN U",
                             scholarship_slot_cap=85)
    athlete = create_student_athlete(sport_code="FOOTBALL", full_name="Ban Cand",
                                     gpa=3.000)
    # A single weight-15 incident (alleged_value >= 2,500,000): total = 15
    # → POSTSEASON_BAN exactly at the boundary.
    report_and_sustain_incident(
        program, athlete, alleged_value_cents=2_500_000, booster_name="Mega",
    )
    prog = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert prog["penalty_tier"] == "POSTSEASON_BAN"


def test_program_penalty_tier_level_two_from_two_sustained_weights(api):
    """PRD §3.7: "one whose value is at least 50,000 but strictly less
    than 500,000 (five thousand dollars) receives 3; one whose value is
    at least 500,000 but strictly less than 2,500,000 (twenty-five
    thousand dollars) receives 7"
    PRD §3.7: "Otherwise, if the total is strictly less than 15, the
    tier is `LEVEL_II`."

    Design: Difficulty/combinatorial_formula/program_penalty_tier_three_input_nonlinear_aggregation
    """
    program = create_program(sport_code="MBB", school_name="Hoops U", scholarship_slot_cap=13)
    athlete = create_student_athlete(sport_code="MBB", full_name="Athlete X", gpa=3.000)

    # First incident: alleged_value_cents=100000 → weight 3.
    report_and_sustain_incident(
        program, athlete, alleged_value_cents=100_000, booster_name="Booster Beta",
    )
    # Second incident: alleged_value_cents=1_000_000 → weight 7. Total 10 → LEVEL_II.
    report_and_sustain_incident(
        program, athlete, alleged_value_cents=1_000_000, booster_name="Booster Gamma",
    )

    prog = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert prog["penalty_tier"] == "LEVEL_II"


def test_nil_value_banker_rounding_at_500000_boundary_high_value(api):
    """PRD §3.5: "exactly 500,000 cents is `HIGH_VALUE`."
    PRD §3.5: "first, `net_value_cents` is the gross value multiplied by
    one minus `agent_fee_pct`, with the resulting cent value rounded to
    the nearest whole cent using banker's rounding (half-to-even). Only
    then is the resulting integer cent count compared against the tier
    cutoffs"

    Design: Difficulty/combinatorial_formula/nil_value_classification_nested_rounding_order
    """
    # gross=500000, fee=0.0 → net = 500000. The boundary at 500000 falls
    # into the higher tier (HIGH_VALUE), confirming the order of operations
    # (round THEN compare) does not exclude exact-boundary equality.
    athlete = setup_certified_athlete(sport_code="WBB", full_name="Boundary 500k",
                                      gpa=3.500)
    res = api.create_nil_deal(
        create_nil_deal_payload(
            student_athlete_id=athlete["id"],
            brand_name="ExactHV",
            gross_value_cents=500000,
            agent_fee_pct=0.0,
        ),
        make_student_athlete_headers(athlete["id"]),
    )
    deal = validate_success(res, 201)
    assert deal["net_value_cents"] == 500000
    assert deal["tier"] == "HIGH_VALUE"


def test_nil_value_banker_rounding_yields_high_value_at_555555_with_fee(api):
    """PRD §3.5: "the net value of a NIL deal — multiplies the gross by
    one minus the agent fee fraction and then rounds to the nearest cent
    using banker's rounding (round half to even). This rounding step is
    applied to the cent value before any tier boundary is evaluated"
    PRD §3.5: "The boundary at exactly 60,000 cents and exactly 500,000
    cents therefore falls into the higher tier — exactly 60,000 cents is
    `STANDARD`, exactly 500,000 cents is `HIGH_VALUE`."

    Design: Difficulty/combinatorial_formula/nil_value_classification_nested_rounding_order
    """
    # gross=555555, fee=0.10 → 555555*0.9 = 499999.5 → banker round → 500000 → HIGH_VALUE
    athlete = setup_certified_athlete(sport_code="WBB", full_name="Athlete Y", gpa=3.300)
    res = api.create_nil_deal(
        create_nil_deal_payload(
            student_athlete_id=athlete["id"],
            brand_name="Energy Co",
            gross_value_cents=555555,
            agent_fee_pct=0.10,
        ),
        make_student_athlete_headers(athlete["id"]),
    )
    deal = validate_success(res, 201)
    assert deal["net_value_cents"] == 500000
    assert deal["tier"] == "HIGH_VALUE"
