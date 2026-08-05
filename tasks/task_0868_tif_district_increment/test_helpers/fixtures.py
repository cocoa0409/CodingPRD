"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken precondition
surfaces as a clear setup failure rather than a confusing assertion error. Every
fixture builds its state from scratch through PRD-declared endpoints, because the
harness restarts the server (empty DB) before every test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_district_payload, create_taxing_body_payload, create_developer_payload,
    create_obligation_payload, register_obligation_payload, accrue_interest_payload,
    create_disbursement_payload, create_increment_record_payload,
    finalize_increment_payload, create_annual_report_payload, accept_report_payload,
    create_surplus_agreement_payload, decertify_payload,
)
from .test_users import (
    TEST_USERS, ADMIN_1_ID, ADMIN_2_ID, make_admin_headers, make_developer_headers,
)

ADMIN = TEST_USERS["municipal_admin_headers"]          # admin-1
ADMIN_2 = TEST_USERS["municipal_admin_2_headers"]      # admin-2
CLERK = TEST_USERS["county_clerk_headers"]

# School .05 + County .02 + City .01 -> aggregate_tax_rate 0.08
DEFAULT_THREE_BODIES = [
    ("School", "SCHOOL", 0.05),
    ("County", "COUNTY", 0.02),
    ("City", "MUNICIPAL", 0.01),
]
SINGLE_SCHOOL_BODY = [("School", "SCHOOL", 0.05)]


# ─── Primitive reads ──────────────────────────────────────────────────────

def district_version(district_id: str) -> int:
    return get_success_data(api_client.get_district(district_id, ADMIN))["version"]

def get_fund(district_id: str) -> dict:
    data = get_success_data(api_client.get_project_fund(district_id, ADMIN))
    return data[0]

def fund_version(district_id: str) -> int:
    return get_fund(district_id)["version"]


# ─── Tier 1/2: District setup ─────────────────────────────────────────────

def create_draft_district(bodies=DEFAULT_THREE_BODIES, **district_overrides):
    """Create a DRAFT district and add its taxing bodies. Returns (district, bodies)."""
    district = get_success_data(
        api_client.create_district(create_district_payload(**district_overrides), ADMIN))
    created_bodies = []
    for name, body_type, rate in bodies:
        tb = get_success_data(api_client.create_taxing_body(
            district["id"],
            create_taxing_body_payload(name=name, body_type=body_type, tax_rate=rate),
            ADMIN))
        created_bodies.append(tb)
    return district, created_bodies


def setup_certified_district(bodies=DEFAULT_THREE_BODIES, **district_overrides) -> dict:
    """Create a district, add bodies, certify it. Returns a context dict with keys
    district, bodies, version (the certified district version)."""
    district, created_bodies = create_draft_district(bodies, **district_overrides)
    certified = get_success_data(api_client.certify_district(district["id"], ADMIN))
    return {"district": certified, "bodies": created_bodies, "version": certified["version"]}


def capture_increment(district_id: str, tax_year: int, current_eav_cents: int) -> dict:
    """CountyClerk captures a provisional increment for a tax year."""
    return get_success_data(api_client.create_increment_record(
        district_id,
        create_increment_record_payload(tax_year, current_eav_cents),
        CLERK))


def create_developer_entity(**overrides) -> dict:
    return get_success_data(api_client.create_developer(
        create_developer_payload(**overrides), ADMIN))


# ─── Tier 3: Obligation lifecycle shortcuts ───────────────────────────────

def propose_submit_bond(district_id, principal_cents=5_000_000, interest_rate_bps=0,
                        issue_tax_year=2026, final_maturity_tax_year=2035,
                        annual_cap_cents=None):
    """Create a BOND, submit it -> UNDER_REVIEW. Returns the obligation."""
    payload = create_obligation_payload(
        district_id, "BOND", principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps, issue_tax_year=issue_tax_year,
        final_maturity_tax_year=final_maturity_tax_year)
    if annual_cap_cents is not None:
        payload["annual_cap_cents"] = annual_cap_cents
    ob = get_success_data(api_client.create_obligation(payload, ADMIN))
    ob = get_success_data(api_client.submit_obligation(ob["id"], ADMIN))
    return ob


def register_bond(district_id, principal_cents=20_000_000, interest_rate_bps=0,
                  issue_tax_year=2026, final_maturity_tax_year=2040,
                  annual_cap_cents=None, priority_rank=1,
                  registrar_id=ADMIN_1_ID) -> dict:
    """Create + submit + register a SENIOR bond (registered by admin-1 by default)."""
    ob = propose_submit_bond(
        district_id, principal_cents=principal_cents, interest_rate_bps=interest_rate_bps,
        issue_tax_year=issue_tax_year, final_maturity_tax_year=final_maturity_tax_year,
        annual_cap_cents=annual_cap_cents)
    return get_success_data(api_client.register_obligation(
        ob["id"],
        register_obligation_payload(priority_rank, district_version(district_id)),
        make_admin_headers(registrar_id)))


def propose_submit_note(district_id, developer_id, principal_cents=5_000_000,
                        interest_rate_bps=0, issue_tax_year=2026,
                        final_maturity_tax_year=2035, annual_cap_cents=None):
    """Create + submit a DEVELOPER_NOTE as its owning developer. Returns obligation."""
    dev_headers = make_developer_headers(developer_id)
    payload = create_obligation_payload(
        district_id, "DEVELOPER_NOTE", developer_id=developer_id,
        principal_cents=principal_cents, interest_rate_bps=interest_rate_bps,
        issue_tax_year=issue_tax_year, final_maturity_tax_year=final_maturity_tax_year)
    if annual_cap_cents is not None:
        payload["annual_cap_cents"] = annual_cap_cents
    ob = get_success_data(api_client.create_obligation(payload, dev_headers))
    ob = get_success_data(api_client.submit_obligation(ob["id"], dev_headers))
    return ob


def register_developer_note(district_id, developer_id, principal_cents=5_000_000,
                            interest_rate_bps=0, issue_tax_year=2026,
                            final_maturity_tax_year=2035, priority_rank=2,
                            registrar_id=ADMIN_1_ID) -> dict:
    """Create + submit (as developer) + register (admin) a SUBORDINATE note."""
    ob = propose_submit_note(
        district_id, developer_id, principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps, issue_tax_year=issue_tax_year,
        final_maturity_tax_year=final_maturity_tax_year)
    return get_success_data(api_client.register_obligation(
        ob["id"],
        register_obligation_payload(priority_rank, district_version(district_id)),
        make_admin_headers(registrar_id)))


def accrue(obligation_id, accrual_tax_year) -> dict:
    return get_success_data(api_client.accrue_interest(
        obligation_id, accrue_interest_payload(accrual_tax_year), ADMIN))


def disburse(obligation_id, amount_cents, disbursement_tax_year, district_id,
             expected_fund_version=None, actor_id=ADMIN_2_ID) -> dict:
    """Disburse against an obligation (default actor admin-2 to satisfy four-eyes)."""
    if expected_fund_version is None:
        expected_fund_version = fund_version(district_id)
    return get_success_data(api_client.create_disbursement(
        obligation_id,
        create_disbursement_payload(amount_cents, disbursement_tax_year,
                                    expected_fund_version),
        make_admin_headers(actor_id)))


# ─── Reports & surplus ────────────────────────────────────────────────────

def add_surplus_agreement(district_id, taxing_body_id, start_tax_year, end_tax_year,
                          surplus_share_ppm_override) -> dict:
    return get_success_data(api_client.create_surplus_agreement(
        district_id,
        create_surplus_agreement_payload(taxing_body_id, start_tax_year, end_tax_year,
                                         surplus_share_ppm_override),
        ADMIN))


def create_and_file_report(district_id, report_tax_year) -> dict:
    report = get_success_data(api_client.create_annual_report(
        district_id, create_annual_report_payload(report_tax_year), CLERK))
    return get_success_data(api_client.file_report(report["id"], CLERK))


def accept_report_now(report_id, district_id, expected_fund_version=None,
                      actor_id=ADMIN_2_ID) -> dict:
    if expected_fund_version is None:
        expected_fund_version = fund_version(district_id)
    return get_success_data(api_client.accept_report(
        report_id, accept_report_payload(expected_fund_version),
        make_admin_headers(actor_id)))


def setup_filed_report_scenario(surplus_policy="GROSS", bodies=DEFAULT_THREE_BODIES,
                                base_eav_cents=100_000_000, increment_tax_year=2026,
                                current_eav_cents=118_750_000, report_tax_year=2027,
                                bond_principal=None, bond_interest_bps=0,
                                bond_issue=2026, bond_maturity=2035,
                                agreements=None) -> dict:
    """Certify a district, optionally add agreements, capture one increment,
    optionally register one SENIOR bond, then create+file an annual report.

    Returns dict: district, bodies, report (FILED), fund_version (current), bond.
    """
    ctx = setup_certified_district(
        bodies=bodies, surplus_policy=surplus_policy, base_eav_cents=base_eav_cents)
    district_id = ctx["district"]["id"]

    for (tb_id, start, end, ppm) in (agreements or []):
        add_surplus_agreement(district_id, tb_id, start, end, ppm)

    capture_increment(district_id, increment_tax_year, current_eav_cents)

    bond = None
    if bond_principal is not None:
        bond = register_bond(
            district_id, principal_cents=bond_principal,
            interest_rate_bps=bond_interest_bps, issue_tax_year=bond_issue,
            final_maturity_tax_year=bond_maturity, priority_rank=1)

    report = create_and_file_report(district_id, report_tax_year)
    ctx.update({"report": report, "bond": bond, "fund_version": fund_version(district_id)})
    return ctx


# ─── Decertification ──────────────────────────────────────────────────────

def decertify(district_id, termination_type, termination_tax_year) -> dict:
    return get_success_data(api_client.decertify_district(
        district_id, decertify_payload(termination_type, termination_tax_year), ADMIN))
