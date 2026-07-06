"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors rather than confusing assertion failures. Every
ownership-gated EmployerAgent call threads the real Employer.id via
make_employer_agent_headers(); opaque roles use the shared constants.

The server database is reset before every test, so each helper builds all of its
preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    employer_payload, pwd_payload, perm_case_payload, recruitment_step_payload,
    lca_payload, beneficiary_payload, cap_program_payload, registration_payload,
    h1b_petition_payload, i140_petition_payload,
)
from .test_users import (
    TEST_USERS, make_employer_agent_headers,
)

DOL = TEST_USERS["dol_analyst_headers"]
USCIS = TEST_USERS["uscis_officer_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
EMPLOYER = TEST_USERS["employer_agent_headers"]


# ─── Primitive builders ───────────────────────────────────────────────────────

def create_employer(**overrides) -> dict:
    """Register an Employer. POST /employers needs no prior owner (PRD §3.1)."""
    res = api_client.create_employer(employer_payload(**overrides), EMPLOYER)
    return get_success_data(res)


def create_beneficiary(employer_id: str, **overrides) -> dict:
    res = api_client.create_beneficiary(
        beneficiary_payload(**overrides), make_employer_agent_headers(employer_id))
    return get_success_data(res)


def create_pending_pwd(employer_id: str, **overrides) -> dict:
    res = api_client.create_pwd(
        pwd_payload(employer_id, **overrides), make_employer_agent_headers(employer_id))
    return get_success_data(res)


def get_employer_version(employer_id: str) -> int:
    """Read the current Employer.version (GET is a shared operation)."""
    return get_success_data(api_client.get_employer(employer_id, DOL))["version"]


def issue_pwd(employer_id: str, pwd_id: str) -> dict:
    """Issue a PENDING PWD using the employer's current version (PRD §3.2).

    Reads the live version first so the OCC guard passes deterministically even
    when a prior issuance already advanced the employer version.
    """
    version = get_employer_version(employer_id)
    res = api_client.transition_pwd(
        pwd_id, {"to_status": "ISSUED", "expected_employer_version": version}, DOL)
    return get_success_data(res)


def create_issued_pwd(employer_id: str, **overrides) -> dict:
    pwd = create_pending_pwd(employer_id, **overrides)
    return issue_pwd(employer_id, pwd["id"])


def create_lca(employer_id: str, **overrides) -> dict:
    res = api_client.create_lca(
        lca_payload(employer_id, **overrides), make_employer_agent_headers(employer_id))
    return get_success_data(res)


def certify_lca(employer_id: str, lca_id: str) -> dict:
    res = api_client.transition_lca(lca_id, {"to_status": "CERTIFIED"}, DOL)
    return get_success_data(res)


def create_certified_lca(employer_id: str, **overrides) -> dict:
    lca = create_lca(employer_id, **overrides)
    return certify_lca(employer_id, lca["id"])


def create_cap_program(fiscal_year: int = 2027, selection_quota: int = 5) -> dict:
    res = api_client.create_cap_program(
        cap_program_payload(fiscal_year, selection_quota), USCIS)
    return get_success_data(res)


def create_registration(employer_id: str, beneficiary_id: str, fiscal_year: int = 2027) -> dict:
    res = api_client.create_registration(
        registration_payload(employer_id, beneficiary_id, fiscal_year),
        make_employer_agent_headers(employer_id))
    return get_success_data(res)


def run_lottery(cap_id: str) -> dict:
    return get_success_data(api_client.run_lottery(cap_id, USCIS))


def set_clock(iso: str) -> dict:
    """Advance the logical clock (any role may set it; PRD §2.4)."""
    return get_success_data(api_client.set_clock(iso, EMPLOYER))


# ─── Tier 2/3: PermCase lifecycle shortcuts ──────────────────────────────────

def create_perm_case(employer_id: str, pwd_id: str, **overrides) -> dict:
    res = api_client.create_perm_case(
        perm_case_payload(employer_id, pwd_id, **overrides),
        make_employer_agent_headers(employer_id))
    return get_success_data(res)


def add_recruitment_step(employer_id: str, perm_case_id: str, **overrides) -> dict:
    res = api_client.create_recruitment_step(
        recruitment_step_payload(perm_case_id, **overrides),
        make_employer_agent_headers(employer_id))
    return get_success_data(res)


def setup_recruiting_perm_case(offered_wage_cents: int = 12000000,
                               oes_wage_cents: int = 10000000):
    """Employer + ISSUED PWD + PermCase transitioned to RECRUITING (PRD §3.3).

    Returns (employer, pwd, perm_case). recruitment_start is stamped to the
    default clock 2026-05-01.
    """
    employer = create_employer()
    pwd = create_issued_pwd(employer["id"], oes_wage_cents=oes_wage_cents)
    perm_case = create_perm_case(employer["id"], pwd["id"], offered_wage_cents=offered_wage_cents)
    hdr = make_employer_agent_headers(employer["id"])
    perm_case = get_success_data(
        api_client.transition_perm_case(perm_case["id"], {"to_status": "RECRUITING"}, hdr))
    return employer, pwd, perm_case


def _add_standard_recruitment_steps(employer_id: str, perm_case_id: str):
    """1 JOB_ORDER + 2 NEWSPAPER_AD ACTIVE steps satisfying PRD §3.3 completeness."""
    add_recruitment_step(employer_id, perm_case_id, step_type="JOB_ORDER",
                         start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    add_recruitment_step(employer_id, perm_case_id, step_type="NEWSPAPER_AD",
                         start_date="2026-05-04T00:00:00Z", end_date="2026-05-04T00:00:00Z")
    add_recruitment_step(employer_id, perm_case_id, step_type="NEWSPAPER_AD",
                         start_date="2026-05-11T00:00:00Z", end_date="2026-05-11T00:00:00Z")


def setup_filed_perm_case(offered_wage_cents: int = 12000000,
                          quiet_clock: str = "2026-06-05T00:00:00Z",
                          file_clock: str = "2026-07-10T00:00:00Z"):
    """Full chain through FILED (PRD §3.3): employer + issued PWD + perm case ->
    RECRUITING -> (steps) -> QUIET_PERIOD (clock quiet_clock) -> FILED (clock
    file_clock). filed_date/priority_date are stamped to file_clock.

    Returns (employer, pwd, perm_case).
    """
    employer, pwd, perm_case = setup_recruiting_perm_case(offered_wage_cents=offered_wage_cents)
    hdr = make_employer_agent_headers(employer["id"])
    _add_standard_recruitment_steps(employer["id"], perm_case["id"])
    set_clock(quiet_clock)
    get_success_data(api_client.transition_perm_case(perm_case["id"], {"to_status": "QUIET_PERIOD"}, hdr))
    set_clock(file_clock)
    perm_case = get_success_data(
        api_client.transition_perm_case(perm_case["id"], {"to_status": "FILED"}, hdr))
    return employer, pwd, perm_case


def setup_quiet_period_perm_case(offered_wage_cents: int = 12000000,
                                 quiet_clock: str = "2026-06-05T00:00:00Z"):
    """Chain to QUIET_PERIOD (PRD §3.3) but NOT filed. quiet_period_end ==
    quiet_clock + 30 days. Leaves the clock at quiet_clock.

    Returns (employer, pwd, perm_case).
    """
    employer, pwd, perm_case = setup_recruiting_perm_case(offered_wage_cents=offered_wage_cents)
    hdr = make_employer_agent_headers(employer["id"])
    _add_standard_recruitment_steps(employer["id"], perm_case["id"])
    set_clock(quiet_clock)
    perm_case = get_success_data(
        api_client.transition_perm_case(perm_case["id"], {"to_status": "QUIET_PERIOD"}, hdr))
    return employer, pwd, perm_case


def setup_certified_perm_case(offered_wage_cents: int = 12000000,
                              quiet_clock: str = "2026-06-05T00:00:00Z",
                              file_clock: str = "2026-07-10T00:00:00Z"):
    """Chain through CERTIFIED (PRD §3.3). priority_date == file_clock.

    Returns (employer, pwd, perm_case).
    """
    employer, pwd, perm_case = setup_filed_perm_case(
        offered_wage_cents=offered_wage_cents, quiet_clock=quiet_clock, file_clock=file_clock)
    perm_case = get_success_data(
        api_client.transition_perm_case(perm_case["id"], {"to_status": "CERTIFIED"}, DOL))
    return employer, pwd, perm_case


# ─── Tier 3: H-1B petition lifecycle shortcuts ───────────────────────────────

def setup_selected_registration(employer_id: str, beneficiary_id: str,
                                fiscal_year: int = 2027, quota: int = 5):
    """Cap program + registration + lottery so the registration is SELECTED.

    Returns (cap_program, registration).
    """
    cap = create_cap_program(fiscal_year, quota)
    reg = create_registration(employer_id, beneficiary_id, fiscal_year)
    run_lottery(cap["id"])
    reg = get_success_data(api_client.get_registration(reg["id"], USCIS))
    return cap, reg


def create_h1b_petition_draft(employer_id: str, lca_id: str, beneficiary_id: str,
                              registration_id: str, **overrides) -> dict:
    res = api_client.create_h1b_petition(
        h1b_petition_payload(employer_id, lca_id, beneficiary_id, registration_id, **overrides),
        make_employer_agent_headers(employer_id))
    return get_success_data(res)


def setup_draft_h1b_petition(lca_certified: bool = True, run_the_lottery: bool = True,
                             fiscal_year: int = 2027, lca_overrides=None,
                             petition_overrides=None, employer_overrides=None):
    """Build a DRAFT H-1B petition with all FKs resolving (PRD §3.6).

    lca_certified / run_the_lottery let callers leave the LCA in DRAFT or the
    registration in SUBMITTED to exercise the cross-entity submit gates.
    employer_overrides tunes employee_count / h1b_dependent for filing-fee tiers.

    Returns dict with keys: employer, beneficiary, lca, cap, registration, petition.
    """
    lca_overrides = lca_overrides or {}
    petition_overrides = petition_overrides or {}
    employer_overrides = employer_overrides or {}
    employer = create_employer(**employer_overrides)
    beneficiary = create_beneficiary(employer["id"])
    lca = create_lca(employer["id"], validity_end="2030-05-01T00:00:00Z", **lca_overrides)
    if lca_certified:
        lca = certify_lca(employer["id"], lca["id"])
    cap = create_cap_program(fiscal_year, 5)
    registration = create_registration(employer["id"], beneficiary["id"], fiscal_year)
    if run_the_lottery:
        run_lottery(cap["id"])
        registration = get_success_data(api_client.get_registration(registration["id"], USCIS))
    petition = create_h1b_petition_draft(
        employer["id"], lca["id"], beneficiary["id"], registration["id"], **petition_overrides)
    return {
        "employer": employer, "beneficiary": beneficiary, "lca": lca,
        "cap": cap, "registration": registration, "petition": petition,
    }


def submit_h1b_petition(employer_id: str, petition_id: str) -> dict:
    hdr = make_employer_agent_headers(employer_id)
    return get_success_data(
        api_client.transition_h1b_petition(petition_id, {"to_status": "SUBMITTED"}, hdr))


def setup_submitted_h1b_petition(fiscal_year: int = 2027, petition_overrides=None):
    """A DRAFT petition driven to SUBMITTED (LCA CERTIFIED, registration SELECTED).

    Returns the same dict as setup_draft_h1b_petition with petition in SUBMITTED.
    """
    ctx = setup_draft_h1b_petition(
        lca_certified=True, run_the_lottery=True, fiscal_year=fiscal_year,
        petition_overrides=petition_overrides)
    ctx["petition"] = submit_h1b_petition(ctx["employer"]["id"], ctx["petition"]["id"])
    return ctx


def setup_two_h1b_petitions_same_beneficiary(pet1_start: str, pet1_end: str,
                                             pet2_start: str, pet2_end: str,
                                             worksite: str = "AREA_A"):
    """One beneficiary + worksite, two petitions across two fiscal-year lotteries.

    petition1 is driven to APPROVED with employment [pet1_start, pet1_end);
    petition2 is left SUBMITTED with employment [pet2_start, pet2_end) so a test
    can approve it and observe the half-open overlap rule (PRD §3.6).

    Returns dict with keys: employer, beneficiary, lca, petition1, petition2.
    """
    employer = create_employer()
    beneficiary = create_beneficiary(employer["id"])
    lca = create_certified_lca(
        employer["id"], worksite_areas=[worksite], area_wage_map={worksite: 10000000},
        validity_end="2031-05-01T00:00:00Z")
    _, reg27 = setup_selected_registration(employer["id"], beneficiary["id"], 2027)
    _, reg28 = setup_selected_registration(employer["id"], beneficiary["id"], 2028)

    pet1 = create_h1b_petition_draft(
        employer["id"], lca["id"], beneficiary["id"], reg27["id"],
        worksite_area=worksite, employment_start=pet1_start, employment_end=pet1_end)
    submit_h1b_petition(employer["id"], pet1["id"])
    pet1 = approve_h1b_petition(pet1["id"])

    pet2 = create_h1b_petition_draft(
        employer["id"], lca["id"], beneficiary["id"], reg28["id"],
        worksite_area=worksite, employment_start=pet2_start, employment_end=pet2_end)
    pet2 = submit_h1b_petition(employer["id"], pet2["id"])
    return {"employer": employer, "beneficiary": beneficiary, "lca": lca,
            "petition1": pet1, "petition2": pet2}


def issue_rfe(petition_id: str) -> dict:
    """USCIS issues an RFE on a SUBMITTED petition (PRD §3.6)."""
    return get_success_data(
        api_client.transition_h1b_petition(petition_id, {"to_status": "RFE_ISSUED"}, USCIS))


def approve_h1b_petition(petition_id: str) -> dict:
    return get_success_data(
        api_client.transition_h1b_petition(petition_id, {"to_status": "APPROVED"}, USCIS))


# ─── Tier 3: I-140 petition shortcuts ────────────────────────────────────────

def create_i140_petition(employer_id: str, beneficiary_id: str, category: str = "EB2",
                         **overrides) -> dict:
    res = api_client.create_i140_petition(
        i140_petition_payload(employer_id, beneficiary_id, category, **overrides),
        make_employer_agent_headers(employer_id))
    return get_success_data(res)


def submit_i140_petition(employer_id: str, petition_id: str) -> dict:
    hdr = make_employer_agent_headers(employer_id)
    return get_success_data(
        api_client.transition_i140_petition(petition_id, {"to_status": "SUBMITTED"}, hdr))
