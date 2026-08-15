"""Band approval gates: overlap clamp, progression boundary, overlap violation,
price/publish transitions, compa recomputation (PRD §3.4-§3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    api_client,
    create_accepted_survey_with_cut,
    create_employee,
    create_pay_band_payload,
    create_price_approve_publish_band,
    create_program,
    create_progression_policy_payload,
    get_success_data,
    setup_framework,
    setup_pricing_program,
    setup_published_band_pair,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]
HRBP = TEST_USERS["hrbp_headers"]


def _three_level_overlap_setup():
    """P1/P2 COMP_APPROVED (mid 10m / 13m, spread 0.30); P3 priced OFFICIAL
    mid 18m spread 0.30 with a P2->P3 policy min_prog 0.1500 max_overlap 0.2000."""
    ctx = setup_pricing_program(
        levels=(("P1", "Engineer I", 1), ("P2", "Engineer II", 2), ("P3", "Engineer III", 3)),
        approve_profiles=(0, 1, 2))
    fam, lvls, zone, prog = ctx["family"], ctx["levels"], ctx["zone"], ctx["program"]
    get_success_data(api_client.create_progression_policy(
        create_progression_policy_payload(fam["id"], lvls[0]["id"], lvls[1]["id"],
                                          min_midpoint_progression_pct=0.1200,
                                          max_overlap_pct=0.2500),
        MANAGER))
    get_success_data(api_client.create_progression_policy(
        create_progression_policy_payload(fam["id"], lvls[1]["id"], lvls[2]["id"],
                                          min_midpoint_progression_pct=0.1500,
                                          max_overlap_pct=0.2000),
        MANAGER))
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], zone["id"], 10_000_000)
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], zone["id"], 13_000_000,
                                    survey_name="S-p2")
    create_accepted_survey_with_cut(ctx["profiles"][3]["id"], zone["id"], 18_000_000,
                                    survey_name="S-p3")
    band1 = create_price_approve_publish_band(prog["id"], fam["id"], lvls[0]["id"],
                                              zone["id"], publish=False)
    band2 = create_price_approve_publish_band(prog["id"], fam["id"], lvls[1]["id"],
                                              zone["id"], publish=False)
    band3 = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fam["id"], lvls[2]["id"], zone["id"],
                                target_percentile="P50", spread_pct=0.3000),
        ANALYST))
    band3 = get_success_data(api_client.price_pay_band(
        band3["id"], {"pricing_variant": "OFFICIAL",
                      "expected_pay_band_version": band3["version"]}, ANALYST))
    return ctx, band1, band2, band3


def test_overlap_report_clamps_negative_raw_to_zero(api):
    """PRD §3.5: "Take the lesser of the two bands' maxima and subtract the
    greater of the two bands' minima; this raw width is negative when the
    bands do not touch, and a negative raw width is clamped so the overlap is
    never below zero."
    PRD §3.5: "The progression figure is the amount by which the candidate
    band's `midpoint_cents` exceeds the lower band's `midpoint_cents`, divided
    by the lower band's midpoint, stored rounded half-up to four decimal
    places; the approval check compares the unrounded ratio against the
    policy's `min_midpoint_progression_pct` — or the ten percent default — and
    passes at or above the floor, so an unrounded ratio of exactly the policy
    minimum passes."

    Design: Difficulty/combinatorial_formula/overlap_clamp_and_guard
    """
    _ctx, _b1, band2, band3 = _three_level_overlap_setup()
    rep = validate_success(api.get_overlap_report(band3["id"], ANALYST), 200)
    assert rep["lower_band_id"] == band2["id"]
    # MIN(14950000,20700000) - MAX(11050000,15300000) = -350000, clamped to 0.
    assert rep["overlap_pct_to_lower"] == pytest.approx(0.0000, abs=1e-9)
    assert rep["progression_pct_from_lower"] == pytest.approx(0.3846, abs=1e-9)


def test_overlap_clamped_band_approve_succeeds(api):
    """PRD §3.5: "The approval check, however, compares the unrounded ratio
    against the policy's `max_overlap_pct` — or the thirty percent default
    where no policy exists — and the band passes when the unrounded ratio is
    no more than the ceiling."
    PRD §3.5: "The progression figure is the amount by which the candidate
    band's `midpoint_cents` exceeds the lower band's `midpoint_cents`, divided
    by the lower band's midpoint, stored rounded half-up to four decimal
    places; the approval check compares the unrounded ratio against the
    policy's `min_midpoint_progression_pct` — or the ten percent default — and
    passes at or above the floor, so an unrounded ratio of exactly the policy
    minimum passes."

    Design: Difficulty/combinatorial_formula/overlap_clamp_and_guard
    """
    _ctx, _b1, _b2, band3 = _three_level_overlap_setup()
    approved = validate_success(api.approve_pay_band(band3["id"], MANAGER), 200)
    assert approved["status"] == "COMP_APPROVED"


def _progression_boundary_setup(p2_p50_cents, family_code="ENG"):
    """One family, P1 band approved mid 10m spread 0.30, P2 priced at the given
    composite with spread 0.05; policy 0.1200/0.2500. NON_EXEMPT profiles."""
    ctx = setup_pricing_program(family_code=family_code, approve_profiles=(0, 1))
    fam, lvls, zone, prog = ctx["family"], ctx["levels"], ctx["zone"], ctx["program"]
    get_success_data(api_client.create_progression_policy(
        create_progression_policy_payload(fam["id"], lvls[0]["id"], lvls[1]["id"],
                                          min_midpoint_progression_pct=0.1200,
                                          max_overlap_pct=0.2500),
        MANAGER))
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], zone["id"], 10_000_000,
                                    survey_name=f"S-{family_code}-p1")
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], zone["id"], p2_p50_cents,
                                    survey_name=f"S-{family_code}-p2")
    band1 = create_price_approve_publish_band(prog["id"], fam["id"], lvls[0]["id"],
                                              zone["id"], publish=False)
    band2 = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fam["id"], lvls[2 - 1]["id"], zone["id"],
                                target_percentile="P50", spread_pct=0.0500),
        ANALYST))
    band2 = get_success_data(api_client.price_pay_band(
        band2["id"], {"pricing_variant": "OFFICIAL",
                      "expected_pay_band_version": band2["version"]}, ANALYST))
    return ctx, band1, band2


def test_progression_exact_boundary_passes(api):
    """PRD §3.5: "The progression figure is the amount by which the candidate
    band's `midpoint_cents` exceeds the lower band's `midpoint_cents`, divided
    by the lower band's midpoint, stored rounded half-up to four decimal
    places; the approval check compares the unrounded ratio against the
    policy's `min_midpoint_progression_pct` — or the ten percent default — and
    passes at or above the floor, so an unrounded ratio of exactly the policy
    minimum passes."

    Design: Corner/calculations/progression_exact_boundary_pass_and_fail
    """
    _ctx, _b1, band2 = _progression_boundary_setup(11_200_000)
    assert band2["midpoint_cents"] == 11_200_000
    approved = validate_success(api.approve_pay_band(band2["id"], MANAGER), 200)
    assert approved["status"] == "COMP_APPROVED"


def test_progression_one_cent_below_boundary_fails(api):
    """PRD §3.5: "Third and fourth are the structural policy checks — overlap
    and progression — evaluated against the band's adjacent-lower neighbor,
    with overlap violations surfacing as `ERR_BAND_OVERLAP_EXCEEDS_POLICY`
    (HTTP 422) and progression shortfalls as `ERR_PROGRESSION_BELOW_POLICY`
    (HTTP 422)."

    Design: Corner/calculations/progression_exact_boundary_pass_and_fail
    """
    _ctx, _b1, band2 = _progression_boundary_setup(11_199_999)
    assert band2["midpoint_cents"] == 11_199_999
    res = api.approve_pay_band(band2["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_PROGRESSION_BELOW_POLICY, expected_status=422)


def test_overlap_exceeds_policy_rejected(api):
    """PRD §3.5: "Third and fourth are the structural policy checks — overlap
    and progression — evaluated against the band's adjacent-lower neighbor,
    with overlap violations surfacing as `ERR_BAND_OVERLAP_EXCEEDS_POLICY`
    (HTTP 422) and progression shortfalls as `ERR_PROGRESSION_BELOW_POLICY`
    (HTTP 422)."

    Design: Corner/errors/overlap_exceeds_policy_rejected
    """
    # NON_EXEMPT profiles keep FLSA out of scope; lax progression floor 0.0100
    # leaves overlap as the only failing check.
    ctx = setup_pricing_program(
        family_code="OPS", family_name="Operations",
        levels=(("O1", "Ops I", 1), ("O2", "Ops II", 2)),
        approve_profiles=(0, 1),
        profile_overrides={"duties_test_passed": False})
    fam, lvls, zone, prog = ctx["family"], ctx["levels"], ctx["zone"], ctx["program"]
    get_success_data(api_client.create_progression_policy(
        create_progression_policy_payload(fam["id"], lvls[0]["id"], lvls[1]["id"],
                                          min_midpoint_progression_pct=0.0100,
                                          max_overlap_pct=0.2500),
        MANAGER))
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], zone["id"], 3_800_000,
                                    sample_size=15, survey_name="S-o1")
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], zone["id"], 4_000_000,
                                    sample_size=15, survey_name="S-o2")
    band1 = create_price_approve_publish_band(prog["id"], fam["id"], lvls[0]["id"],
                                              zone["id"], publish=False)
    band2 = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fam["id"], lvls[1]["id"], zone["id"]),
        ANALYST))
    band2 = get_success_data(api_client.price_pay_band(
        band2["id"], {"pricing_variant": "OFFICIAL",
                      "expected_pay_band_version": band2["version"]}, ANALYST))
    res = api.approve_pay_band(band2["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_BAND_OVERLAP_EXCEEDS_POLICY, expected_status=422)
    after = validate_success(api.get_pay_band(band2["id"], MANAGER), 200)
    assert after["status"] == "PRICED"


def test_price_published_band_rejected(api):
    """PRD §3.4: "Three gates precede the computation, in the precedence order
    of §2.8: the stale-version guard first, then the posture gate requiring
    the band's program to be in `PRICING` or `MAPPING_OPEN` (mid-exercise
    repricing is legitimate, so an open mapping posture does not block a price
    call), then transition legality — pricing is declared only from `DRAFT` or
    `PRICED`, and a re-price from `PRICED` overwrites the previously recorded
    `pricing_variant`."
    PRD §2.8 tier 7: "The requested action must be declared for the entity's
    current state (`ERR_INVALID_STATE_TRANSITION`, HTTP 409); an entity
    already in a terminal state accepts no further transitions
    (`ERR_ALREADY_TERMINAL`, HTTP 409)."

    Design: Corner/state_machines/price_published_band_rejected
    """
    ctx = setup_pricing_program(approve_profiles=(0,))
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], ctx["zone"]["id"],
                                    10_000_000)
    band = create_price_approve_publish_band(
        ctx["program"]["id"], ctx["family"]["id"], ctx["levels"][0]["id"],
        ctx["zone"]["id"])
    assert band["status"] == "PUBLISHED"
    res = api.price_pay_band(
        band["id"], {"pricing_variant": "OFFICIAL",
                     "expected_pay_band_version": band["version"]}, ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_pay_band(band["id"], ANALYST), 200)
    assert after["status"] == "PUBLISHED"
    assert after["midpoint_cents"] == 10_000_000


def test_band_created_in_draft_with_null_pricing_fields(api):
    """PRD §3.4: "A new band opens in `DRAFT` with `pricing_variant` null and
    with `market_composite_cents`, `composite_cut_count`, `midpoint_cents`,
    `min_cents`, `max_cents`, `geo_ratio_snapshot`, and `priced_at` all unset
    until the first pricing."

    Design: Corner/state_machines/band_created_in_draft
    """
    fw = setup_framework()
    prog = create_program()
    band = validate_success(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fw["family"]["id"],
                                fw["levels"][0]["id"], fw["zone"]["id"]),
        ANALYST), 201)
    assert band["status"] == "DRAFT"
    assert band["midpoint_cents"] is None
    assert band["min_cents"] is None
    assert band["max_cents"] is None
    assert band["pricing_variant"] is None
    assert band["version"] == 1


def test_publish_recomputes_employee_compa(api):
    """PRD §3.5: "Upon publication the system recomputes `compa_ratio` and
    `range_position` (§3.6) for every `ACTIVE` employee whose job profile
    shares the band's family and level and whose `geo_zone_id` matches the
    band's."
    PRD §3.6: "When a band resolves, the `compa_ratio` is the
    `base_salary_cents` divided by the band's `midpoint_cents`, rounded
    half-up to four decimal places, and the `range_position` is `BELOW_MIN`
    when the salary falls below the band's `min_cents`, `ABOVE_MAX` when it
    exceeds the band's `max_cents`, and `IN_RANGE` otherwise — a salary
    exactly at either edge lands `IN_RANGE`."

    Design: Corner/state_machines/publish_recomputes_employee_compa
    """
    ctx = setup_pricing_program(approve_profiles=(1,))
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], ctx["zone"]["id"],
                                    13_000_000)
    band = create_price_approve_publish_band(
        ctx["program"]["id"], ctx["family"]["id"], ctx["levels"][1]["id"],
        ctx["zone"]["id"], publish=False)
    assert band["status"] == "COMP_APPROVED"
    from test_helpers import create_department_payload, create_employee_payload
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    emp = get_success_data(api_client.create_employee(
        create_employee_payload(dept["id"], ctx["profiles"][2]["id"],
                                ctx["zone"]["id"], base_salary_cents=14_000_000,
                                hire_date="2019-05-01", employee_ref="E1"),
        HRBP))
    assert emp["compa_ratio"] is None
    assert emp["range_position"] == "UNBANDED"
    pre_version = emp["version"]
    validate_success(api.publish_pay_band(band["id"], MANAGER), 200)
    after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert after["compa_ratio"] == pytest.approx(1.0769, abs=1e-9)
    assert after["range_position"] == "IN_RANGE"
    assert after["red_circled"] is False
    assert after["version"] > pre_version


def test_compa_ratio_precision_and_range_position(api):
    """PRD §3.6: "When a band resolves, the `compa_ratio` is the
    `base_salary_cents` divided by the band's `midpoint_cents`, rounded
    half-up to four decimal places, and the `range_position` is `BELOW_MIN`
    when the salary falls below the band's `min_cents`, `ABOVE_MAX` when it
    exceeds the band's `max_cents`, and `IN_RANGE` otherwise — a salary
    exactly at either edge lands `IN_RANGE`."

    Design: Corner/calculations/compa_ratio_precision_and_range_position
    """
    ctx = setup_pricing_program(approve_profiles=(1,))
    create_accepted_survey_with_cut(ctx["profiles"][2]["id"], ctx["zone"]["id"],
                                    13_000_000)
    create_price_approve_publish_band(
        ctx["program"]["id"], ctx["family"]["id"], ctx["levels"][1]["id"],
        ctx["zone"]["id"])
    from test_helpers import create_department_payload, create_employee_payload
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    eb = validate_success(api_client.create_employee(
        create_employee_payload(dept["id"], ctx["profiles"][2]["id"],
                                ctx["zone"]["id"], base_salary_cents=10_000_000,
                                hire_date="2020-01-15", employee_ref="EB"),
        HRBP), 201)
    assert eb["compa_ratio"] == pytest.approx(0.7692, abs=1e-9)
    assert eb["range_position"] == "BELOW_MIN"
    em = validate_success(api_client.create_employee(
        create_employee_payload(dept["id"], ctx["profiles"][2]["id"],
                                ctx["zone"]["id"], base_salary_cents=11_050_000,
                                hire_date="2021-01-15", employee_ref="EM"),
        HRBP), 201)
    assert em["compa_ratio"] == pytest.approx(0.8500, abs=1e-9)
    assert em["range_position"] == "IN_RANGE"


def test_analyst_cannot_approve_band(api):
    """PRD §2.1: "Every endpoint declares the roles permitted to call it; an
    authenticated caller whose role is not listed for the endpoint is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /comp/pay-bands/{id}/approve lists only CompManager.

    Design: Corner/rbac/analyst_cannot_approve_band
    """
    ctx = setup_pricing_program(approve_profiles=(0,))
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], ctx["zone"]["id"],
                                    10_000_000)
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], ctx["family"]["id"],
                                ctx["levels"][0]["id"], ctx["zone"]["id"]),
        ANALYST))
    band = get_success_data(api_client.price_pay_band(
        band["id"], {"pricing_variant": "OFFICIAL",
                     "expected_pay_band_version": band["version"]}, ANALYST))
    res = api.approve_pay_band(band["id"], ANALYST)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    after = validate_success(api.get_pay_band(band["id"], ANALYST), 200)
    assert after["status"] == "PRICED"
