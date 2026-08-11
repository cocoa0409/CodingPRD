"""Composite setup helpers for multi-step test prerequisites.

All helpers build state exclusively through PRD-declared endpoints and use
the lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: Family calls are ownership-gated (PRD §2.1), so every
Family call uses make_family_headers(student["id"]) — never the shared
TEST_USERS["family_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BOOT_ISO
from .factories import (
    create_assignment_payload,
    create_asset_unit_payload,
    create_audit_sweep_payload,
    create_damage_report_payload,
    create_fleet_payload,
    create_insurance_policy_payload,
    create_loaner_checkout_payload,
    create_program_payload,
    create_student_payload,
    return_assignment_payload,
    sign_agreement_payload,
)
from .test_users import TEST_USERS, make_family_headers

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


# ─── Tier 1: State progression ──────────────────────────────────────

def create_program(**overrides):
    """Create a DistrictProgram (starts in DRAFT). Returns the program."""
    res = api_client.create_program(create_program_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_fleet(prog_id, **overrides):
    """Create an AssetFleet under a program. Returns the fleet."""
    res = api_client.create_fleet(prog_id, create_fleet_payload(**overrides), ADMIN)
    return get_success_data(res)


def activate_program(prog_id):
    """DRAFT -> ACTIVE. Returns the activated program."""
    return get_success_data(api_client.activate_program(prog_id, ADMIN))


def set_clock(to_iso8601):
    """Advance the server's logical clock (PRD §2.8). Returns response data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def intake_asset(prog_id, fleet_id, barcode="BC-0001", serial="SN-0001", grade=None):
    """Intake an AssetUnit (READY). grade=None omits condition_grade (server
    applies its default). Returns the unit."""
    payload = create_asset_unit_payload(barcode, serial)
    if grade is not None:
        payload["condition_grade"] = grade
    res = api_client.create_asset_unit(prog_id, fleet_id, payload, TECH)
    return get_success_data(res)


# ─── Tier 2: Entity hierarchy ───────────────────────────────────────

def setup_active_program_with_fleet(program_overrides=None, fleet_overrides=None):
    """Active program + one fleet. Returns (program, fleet)."""
    program = create_program(**(program_overrides or {}))
    fleet = create_fleet(program["id"], **(fleet_overrides or {}))
    program = activate_program(program["id"])
    return program, fleet


def setup_program_fleet_assets(n_assets=1, program_overrides=None,
                               fleet_overrides=None, asset_grade=None,
                               barcode_prefix="BC", serial_prefix="SN"):
    """Active program + fleet + N READY units. Returns (program, fleet, assets)."""
    program, fleet = setup_active_program_with_fleet(
        program_overrides, fleet_overrides
    )
    assets = []
    for i in range(n_assets):
        assets.append(
            intake_asset(
                program["id"], fleet["id"],
                barcode=f"{barcode_prefix}-{i + 1:04d}",
                serial=f"{serial_prefix}-{i + 1:04d}",
                grade=asset_grade,
            )
        )
    return program, fleet, assets


def enroll_student(prog_id, external_id="SIS-0001", full_name="Test Student",
                   free_lunch=None):
    """Enroll a student. free_lunch=None omits the flag (server default)."""
    payload = create_student_payload(external_id, full_name)
    if free_lunch is not None:
        payload["free_lunch_eligible"] = free_lunch
    return get_success_data(api_client.create_student(prog_id, payload, REGISTRAR))


def sign_agreement(prog_id, student_id, **overrides):
    """FamilyAgreement PENDING -> SIGNED (Family, ownership-gated)."""
    res = api_client.sign_family_agreement(
        prog_id, student_id, sign_agreement_payload(**overrides),
        make_family_headers(student_id),
    )
    return get_success_data(res)


def refresh_student(prog_id, student_id):
    """Re-read a student (picks up version / derived-field changes)."""
    return get_success_data(api_client.get_student(prog_id, student_id, REGISTRAR))


def enroll_signed_student(prog_id, external_id="SIS-0001",
                          full_name="Test Student", free_lunch=False):
    """Enroll + sign the family agreement. Returns the fresh student."""
    student = enroll_student(prog_id, external_id, full_name, free_lunch)
    sign_agreement(prog_id, student["id"])
    return refresh_student(prog_id, student["id"])


# ─── Tier 3: Full lifecycle shortcuts ───────────────────────────────

def create_assignment_for(prog_id, student_id, asset_id,
                          expected_return_date="2027-06-01T00:00:00Z"):
    """Create an Assignment, first refreshing the student's version for the
    required expected_student_version (PRD §2.7). Returns the assignment."""
    student = refresh_student(prog_id, student_id)
    payload = create_assignment_payload(
        asset_id, student["version"], expected_return_date=expected_return_date
    )
    return get_success_data(
        api_client.create_assignment(prog_id, student_id, payload, REGISTRAR)
    )


def setup_student_with_assignment(free_lunch=False, asset_grade="A",
                                  expected_return_date="2027-06-01T00:00:00Z",
                                  program_overrides=None, fleet_overrides=None,
                                  external_id="SIS-0001"):
    """Active program + fleet + one READY unit + signed student + ACTIVE
    assignment. Returns a context dict."""
    program, fleet, assets = setup_program_fleet_assets(
        n_assets=1,
        program_overrides=program_overrides,
        fleet_overrides=fleet_overrides,
        asset_grade=asset_grade,
    )
    student = enroll_signed_student(prog_id=program["id"], external_id=external_id,
                                    free_lunch=free_lunch)
    assignment = create_assignment_for(
        program["id"], student["id"], assets[0]["id"],
        expected_return_date=expected_return_date,
    )
    return {
        "program": program, "fleet": fleet, "asset": assets[0],
        "student": refresh_student(program["id"], student["id"]),
        "assignment": assignment,
    }


def file_damage_report(ctx, damage_category="COSMETIC", observed_condition_grade="A",
                       as_technician=False):
    """File a DamageReport on the context's assignment (DRAFT). Returns it."""
    headers = TECH if as_technician else make_family_headers(ctx["student"]["id"])
    res = api_client.create_damage_report(
        ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
        create_damage_report_payload(
            damage_category=damage_category,
            observed_condition_grade=observed_condition_grade,
        ),
        headers,
    )
    return get_success_data(res)


def submit_damage_report(ctx, report_id):
    """DamageReport DRAFT -> SUBMITTED (Family, ownership-gated)."""
    res = api_client.submit_damage_report(
        ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
        report_id, make_family_headers(ctx["student"]["id"]),
    )
    return get_success_data(res)


def confirm_damage_report(ctx, report_id):
    """DamageReport SUBMITTED -> CONFIRMED (SiteTechnician)."""
    res = api_client.confirm_damage_report(
        ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
        report_id, TECH,
    )
    return get_success_data(res)


def list_fees(ctx):
    return get_success_data(
        api_client.list_fees(ctx["program"]["id"], ctx["student"]["id"], ADMIN)
    )


def setup_confirmed_damage_fee(damage_category="COSMETIC",
                               observed_condition_grade="A", free_lunch=False,
                               asset_grade="A", insurance=None,
                               expected_return_date="2027-06-01T00:00:00Z",
                               fleet_overrides=None):
    """Full chain through a CONFIRMED damage report with its FeeAssessment.

    insurance: None or dict(deductible_cents=..., coverage_cap_cents=...).
    Returns ctx dict extended with report, fee, policy keys.
    """
    ctx = setup_student_with_assignment(
        free_lunch=free_lunch, asset_grade=asset_grade,
        expected_return_date=expected_return_date,
        fleet_overrides=fleet_overrides,
    )
    policy = None
    if insurance is not None:
        policy = add_active_insurance(
            ctx["program"]["id"], ctx["student"]["id"], **insurance
        )
    report = file_damage_report(
        ctx, damage_category=damage_category,
        observed_condition_grade=observed_condition_grade,
    )
    submit_damage_report(ctx, report["id"])
    report = confirm_damage_report(ctx, report["id"])
    fees = list_fees(ctx)
    ctx.update({
        "report": report,
        "fees": fees,
        "fee": fees[0] if fees else None,
        "policy": policy,
        "student": refresh_student(ctx["program"]["id"], ctx["student"]["id"]),
    })
    return ctx


# ─── Insurance ──────────────────────────────────────────────────────

def add_active_insurance(prog_id, student_id, premium_cents=5000,
                         deductible_cents=2500, coverage_cap_cents=50000,
                         academic_year="2026-2027"):
    """Create + activate an InsurancePolicy (Family, ownership-gated)."""
    headers = make_family_headers(student_id)
    policy = get_success_data(api_client.create_insurance_policy(
        prog_id, student_id,
        create_insurance_policy_payload(
            premium_cents=premium_cents, deductible_cents=deductible_cents,
            coverage_cap_cents=coverage_cap_cents, academic_year=academic_year,
        ),
        headers,
    ))
    return get_success_data(
        api_client.activate_insurance_policy(
            prog_id, student_id, policy["id"], headers
        )
    )


# ─── Tier 4: Threshold / pool targeting ─────────────────────────────

def designate_loaner(prog_id, asset_id):
    """READY -> LOANER (SiteTechnician)."""
    return get_success_data(api_client.designate_loaner(prog_id, asset_id, TECH))


def setup_loaner_pool(n_units, n_loaners, threshold_pct=0.10):
    """Active program (given loaner floor) + fleet + n_units READY units,
    the first n_loaners of them designated LOANER. Returns (program, fleet,
    loaner_units, other_units)."""
    program, fleet, assets = setup_program_fleet_assets(
        n_assets=n_units, program_overrides={"loaner_pool_threshold_pct": threshold_pct},
    )
    loaners = [designate_loaner(program["id"], a["id"]) for a in assets[:n_loaners]]
    return program, fleet, loaners, assets[n_loaners:]


# ─── Tier 5: End-of-life / audit terminal states ────────────────────

def retire_asset(prog_id, asset_id):
    """READY|DEPLOYED -> END_OF_LIFE, threading expected_asset_unit_version
    (PRD §2.7). Returns the retired unit."""
    asset = get_success_data(api_client.get_asset_unit(prog_id, asset_id, ADMIN))
    return get_success_data(api_client.retire_asset_unit(
        prog_id, asset_id, {"expected_asset_unit_version": asset["version"]}, ADMIN
    ))


def setup_retired_unit(useful_life_months=12, in_service_date="2025-05-01T00:00:00Z",
                       clock_after_setup="2026-06-01T00:00:00Z", asset_grade="C"):
    """Active program whose fleet is old enough that, after the clock advance,
    months_in_service >= useful_life_months; unit retired to END_OF_LIFE.
    Returns (program, fleet, asset)."""
    program, fleet, assets = setup_program_fleet_assets(
        n_assets=1,
        fleet_overrides={
            "useful_life_months": useful_life_months,
            "in_service_date": in_service_date,
        },
        asset_grade=asset_grade,
    )
    if clock_after_setup is not None:
        set_clock(clock_after_setup)
    retired = retire_asset(program["id"], assets[0]["id"])
    return program, fleet, retired


def setup_closed_sweep(program, scanned_barcodes):
    """Create -> begin -> scan each barcode -> finish-scan -> close.
    Returns the CLOSED sweep. Requires every expected unit to be scanned
    (PRD §3.9)."""
    prog = get_success_data(api_client.get_program(program["id"], ADMIN))
    sweep = get_success_data(api_client.create_audit_sweep(
        program["id"], create_audit_sweep_payload(prog["version"]), ADMIN
    ))
    sweep = get_success_data(api_client.begin_audit_sweep(program["id"], sweep["id"], ADMIN))
    for barcode in scanned_barcodes:
        get_success_data(api_client.scan_audit_sweep(
            program["id"], sweep["id"], {"asset_tag_barcode": barcode}, TECH
        ))
    sweep = get_success_data(
        api_client.finish_scan_audit_sweep(program["id"], sweep["id"], ADMIN)
    )
    return get_success_data(
        api_client.close_audit_sweep(program["id"], sweep["id"], ADMIN)
    )


# ─── Loaner checkout helpers ────────────────────────────────────────

def create_loaner_checkout_for(prog_id, student_id, **overrides):
    """Create a LoanerCheckout (SiteTechnician). Returns the checkout."""
    res = api_client.create_loaner_checkout(
        prog_id, student_id, create_loaner_checkout_payload(**overrides), TECH
    )
    return get_success_data(res)


def get_loaner_checkout(prog_id, student_id, checkout_id):
    return get_success_data(
        api_client.get_loaner_checkout(prog_id, student_id, checkout_id, ADMIN)
    )
