"""Composite setup helpers for multi-step test prerequisites.

Fixtures use get_success_data() (lenient) so setup failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.
Every test starts against an empty database (the harness restarts the
server per test), so each fixture builds its preconditions from scratch
using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_department_payload,
    create_employee_payload,
    create_geo_zone_payload,
    create_job_family_payload,
    create_job_level_payload,
    create_job_profile_payload,
    create_mapping_decision_payload,
    create_market_cut_payload,
    create_market_survey_payload,
    create_pay_band_payload,
    create_program_payload,
    create_progression_policy_payload,
    create_refresh_cycle_payload,
)
from .test_users import TEST_USERS, make_department_manager_headers

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]
MANAGER2 = TEST_USERS["comp_manager_2_headers"]
HRBP = TEST_USERS["hrbp_headers"]
FINANCE = TEST_USERS["finance_partner_headers"]


# ─── Tier 1: framework primitives ─────────────────────────────────────

def setup_framework(family_code="ENG", family_name="Engineering",
                    levels=(("P1", "Engineer I", 1), ("P2", "Engineer II", 2)),
                    zone_code="US-NAT", zone_ratio=1.000000):
    """Create a job family, job levels, and a root geo zone.

    Returns dict with keys: family, levels (list in creation order), zone.
    """
    family = get_success_data(
        api_client.create_job_family(
            create_job_family_payload(code=family_code, name=family_name), ADMIN))
    lvl_list = []
    for code, title, rank in levels:
        lvl_list.append(get_success_data(
            api_client.create_job_level(
                create_job_level_payload(level_code=code, title=title, rank_order=rank),
                ADMIN)))
    zone = get_success_data(
        api_client.create_geo_zone(
            create_geo_zone_payload(zone_code=zone_code, name="US National",
                                    differential_ratio=zone_ratio),
            ADMIN))
    return {"family": family, "levels": lvl_list, "zone": zone}


def create_child_zone(zone_code, name, ratio, parent_id):
    """Create a geo zone under a parent. Returns the zone."""
    return get_success_data(api_client.create_geo_zone(
        create_geo_zone_payload(zone_code=zone_code, name=name,
                                differential_ratio=ratio, parent_zone_id=parent_id),
        ADMIN))


def create_approved_profile(family_id, level_id, title=None,
                            salary_basis_weekly_cents=200_000,
                            duties_test_passed=True):
    """Create a profile and walk it DRAFT -> APPROVED (determine, submit, approve)."""
    profile = get_success_data(api_client.create_job_profile(
        create_job_profile_payload(
            family_id, level_id,
            title=title or "Job",
            salary_basis_weekly_cents=salary_basis_weekly_cents,
            duties_test_passed=duties_test_passed),
        ANALYST))
    api_client.determine_flsa(profile["id"], ANALYST)
    api_client.submit_job_profile(profile["id"], ANALYST)
    return get_success_data(api_client.approve_job_profile(profile["id"], MANAGER))


def create_program(**overrides):
    """Create a CompProgram (DRAFT)."""
    return get_success_data(api_client.create_program(
        create_program_payload(**overrides), ADMIN))


def advance_program(program_id, to_state):
    """POST a program transition; returns updated program."""
    return get_success_data(api_client.transition_program(
        program_id, {"to_state": to_state}, ADMIN))


def create_accepted_survey_with_cut(profile_id, zone_id, p50_cents,
                                    sample_size=20, effective_date="2026-08-01",
                                    survey_year=2026, survey_name=None,
                                    survey_effective_date=None):
    """Create survey, accept it, then attach one cut. Returns (survey, cut)."""
    survey = get_success_data(api_client.create_market_survey(
        create_market_survey_payload(
            name=survey_name or "S", survey_year=survey_year,
            effective_date=survey_effective_date or effective_date),
        ANALYST))
    get_success_data(api_client.accept_market_survey(survey["id"], MANAGER))
    cut = get_success_data(api_client.create_market_cut(
        create_market_cut_payload(survey["id"], profile_id, zone_id,
                                  p50_cents=p50_cents, sample_size=sample_size,
                                  effective_date=effective_date),
        ANALYST))
    return survey, cut


# ─── Tier 2: program in PRICING with approved profile(s) ──────────────

def setup_pricing_program(family_code="ENG",
                          family_name="Engineering",
                          levels=(("P1", "Engineer I", 1), ("P2", "Engineer II", 2)),
                          approve_profiles=(1,),  # indexes into levels to create+approve profiles for
                          program_overrides=None,
                          profile_overrides=None):
    """Framework + approved profiles + program advanced to PRICING.

    Returns dict: family, levels, zone, profiles (dict rank -> profile), program.
    """
    fw = setup_framework(family_code=family_code, family_name=family_name, levels=levels)
    profiles = {}
    for idx in approve_profiles:
        lvl = fw["levels"][idx]
        profiles[lvl["rank_order"]] = create_approved_profile(
            fw["family"]["id"], lvl["id"],
            title=f"Profile {lvl['level_code']}", **(profile_overrides or {}))
    program = create_program(**(program_overrides or {}))
    advance_program(program["id"], "FRAMEWORK_LOCKED")
    program = advance_program(program["id"], "PRICING")
    return {**fw, "profiles": profiles, "program": program}


# ─── Tier 3: priced / published bands ─────────────────────────────────

def create_price_approve_publish_band(program_id, family_id, level_id, zone_id,
                                      target_percentile="P50", spread_pct=0.3000,
                                      publish=True, approve=True):
    """Create a band, price it OFFICIAL, approve, optionally publish.

    Caller must ensure a pricing candidate set exists beforehand.
    Returns the band in its final state.
    """
    band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(program_id, family_id, level_id, zone_id,
                                target_percentile=target_percentile, spread_pct=spread_pct),
        ANALYST))
    band = get_success_data(api_client.price_pay_band(
        band["id"], {"pricing_variant": "OFFICIAL",
                     "expected_pay_band_version": band["version"]},
        ANALYST))
    if approve:
        band = get_success_data(api_client.approve_pay_band(band["id"], MANAGER))
    if publish:
        band = get_success_data(api_client.publish_pay_band(band["id"], MANAGER))
    return band


def setup_published_band_pair(p1_p50=10_000_000, p2_p50=13_000_000,
                              spread_pct=0.3000, pool_cents=5_000_000,
                              cut_effective_date="2026-08-01",
                              program_overrides=None):
    """Two-level ENG scenario: P1 + P2 bands PUBLISHED; program left in MAPPING_OPEN.

    Returns dict with family, levels, zone, profiles, program, band1, band2,
    department, survey.
    """
    ctx = setup_pricing_program(approve_profiles=(0, 1),
                                program_overrides=program_overrides)
    fam, lvls, zone, prog = ctx["family"], ctx["levels"], ctx["zone"], ctx["program"]
    p1, p2 = ctx["profiles"][1], ctx["profiles"][2]
    survey, _c1 = create_accepted_survey_with_cut(p1["id"], zone["id"], p1_p50,
                                                  effective_date=cut_effective_date)
    _s, _c2 = create_accepted_survey_with_cut(p2["id"], zone["id"], p2_p50,
                                              effective_date=cut_effective_date,
                                              survey_name="S-p2")
    band1 = create_price_approve_publish_band(
        prog["id"], fam["id"], lvls[0]["id"], zone["id"], spread_pct=spread_pct)
    band2 = create_price_approve_publish_band(
        prog["id"], fam["id"], lvls[1]["id"], zone["id"], spread_pct=spread_pct)
    prog = advance_program(prog["id"], "MAPPING_OPEN")
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA",
                                  adjustment_pool_cents=pool_cents),
        ADMIN))
    return {**ctx, "program": prog, "band1": band1, "band2": band2,
            "department": dept, "survey": survey}


def setup_published_program(p1_p50=10_000_000, p2_p50=13_000_000,
                            spread_pct=0.3000, pool_cents=5_000_000,
                            program_overrides=None):
    """Published band pair + program advanced to PUBLISHED."""
    ctx = setup_published_band_pair(p1_p50=p1_p50, p2_p50=p2_p50,
                                    spread_pct=spread_pct, pool_cents=pool_cents,
                                    program_overrides=program_overrides)
    prog = advance_program(ctx["program"]["id"], "PUBLISHED")
    ctx["program"] = prog
    return ctx


def create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                    hire_date="2020-01-15", employee_ref="E1"):
    """Create an employee inside a scenario ctx (uses ctx's dept/zone/profiles)."""
    return get_success_data(api_client.create_employee(
        create_employee_payload(ctx["department"]["id"],
                                ctx["profiles"][profile_rank]["id"],
                                ctx["zone"]["id"],
                                base_salary_cents=base_salary_cents,
                                hire_date=hire_date, employee_ref=employee_ref),
        HRBP))


# ─── Tier 4: mapping decision pipeline ────────────────────────────────

def create_submitted_mapping(ctx, employee, to_profile):
    """Create + submit a mapping decision as the owning DepartmentManager."""
    dept_id = ctx["department"]["id"]
    headers = make_department_manager_headers(dept_id)
    md = get_success_data(api_client.create_mapping_decision(
        create_mapping_decision_payload(employee["id"], to_profile["id"]), headers))
    md = get_success_data(api_client.submit_mapping_decision(md["id"], headers))
    return md


def create_triaged_mapping(ctx, employee, to_profile):
    """Mapping decision walked to COMP_TRIAGED (submit, hrbp-review, comp-triage)."""
    md = create_submitted_mapping(ctx, employee, to_profile)
    md = get_success_data(api_client.hrbp_review_mapping_decision(md["id"], HRBP))
    md = get_success_data(api_client.comp_triage_mapping_decision(md["id"], ANALYST))
    return md


# ─── Tier 5: exception request pipeline ───────────────────────────────

def create_exception(ctx, employee, band, requested_salary_cents,
                     ex_type="OFF_CYCLE_INCREASE", justification="retention"):
    """Create an exception request as the owning DepartmentManager."""
    headers = make_department_manager_headers(ctx["department"]["id"])
    return get_success_data(api_client.create_exception_request(
        {
            "employee_id": employee["id"],
            "pay_band_id": band["id"],
            "type": ex_type,
            "requested_salary_cents": requested_salary_cents,
            "justification": justification,
        },
        headers))


def approve_exception_via_comp_gate(ctx, employee, band, requested_salary_cents,
                                    ex_type="OFF_CYCLE_INCREASE"):
    """Create + hrbp-pass + comp-pass (non-finance branch lands APPROVED)."""
    xr = create_exception(ctx, employee, band, requested_salary_cents, ex_type=ex_type)
    xr = get_success_data(api_client.hrbp_pass_exception_request(xr["id"], HRBP))
    xr = get_success_data(api_client.comp_pass_exception_request(xr["id"], MANAGER))
    return xr


# ─── Tier 6: refresh cycle pipeline ───────────────────────────────────

def setup_refresh_approved(ctx, window_start="2027-01-01", window_end="2027-03-01",
                           effective_date="2027-01-01"):
    """On a PUBLISHED program: schedule cycle, compute impact, finance-approve.

    Returns (cycle, impact_response_data).
    """
    rc = get_success_data(api_client.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"],
                                     planned_window_start=window_start,
                                     planned_window_end=window_end,
                                     effective_date=effective_date),
        MANAGER))
    rc = get_success_data(api_client.compute_refresh_impact(rc["id"], ANALYST))
    rc = get_success_data(api_client.approve_refresh_cycle(rc["id"], FINANCE))
    return rc


def set_clock(iso_ts):
    """Advance the server logical clock (PRD §2.6)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": iso_ts}, ADMIN))


def current_program_version(program_id):
    """Re-read a program's current version (OCC guard for refresh apply)."""
    return get_success_data(api_client.get_program(program_id, ADMIN))["version"]
