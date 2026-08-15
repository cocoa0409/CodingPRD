"""Composite setup helpers for multi-step test prerequisites.

All helpers build state from an empty database using only PRD-declared
endpoints, and use get_success_data() (lenient) so a setup failure surfaces as
a clear "setup failed" error rather than a confusing assertion failure.

Identity threading: PrincipalInvestigator / ResearchStaff are entity-backed
roles (PRD §2.1) — any ownership-gated call (statement certify, PI report
submit) uses make_pi_headers(person_id) / make_research_staff_headers(person_id)
with the actual Person.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_sponsor_payload, create_person_payload, create_award_payload,
    create_budget_line_payload, create_effort_commitment_payload,
    create_expenditure_payload, create_salary_expenditure_payload,
    create_cost_transfer_payload, create_effort_cycle_payload,
    create_subaward_payload, create_subaward_invoice_payload,
    create_report_requirement_payload, create_drawdown_request_payload,
    create_receivable_payload, create_modification_request_payload,
)
from .test_users import TEST_USERS, make_pi_headers, make_research_staff_headers
from .constants import TEST_DEFAULTS

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]
GA2 = TEST_USERS["accountant_2_headers"]
SO = TEST_USERS["sponsor_official_headers"]
ADMIN = TEST_USERS["system_admin_headers"]

_PROJECT_START = "2026-01-01T00:00:00Z"
_END_2026 = "2026-12-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: atomic creates
# ---------------------------------------------------------------------------

def make_sponsor(payment_method="LETTER_OF_CREDIT", name="NSF-LOC", **overrides):
    """Create a sponsor. Payment method is inherited by every award under it
    (PRD §3.1)."""
    payload = create_sponsor_payload(name=name, payment_method=payment_method, **overrides)
    return get_success_data(api_client.create_sponsor(payload, SPO))


def make_person(role_type="PRINCIPAL_INVESTIGATOR", ibs=12_000_000,
                appointment_months=12, full_name="Dr. Prime"):
    payload = create_person_payload(
        full_name=full_name, role_type=role_type,
        institutional_base_salary_annual_cents=ibs,
        appointment_months=appointment_months)
    return get_success_data(api_client.create_person(payload, SPO))


def make_award(sponsor_id, pi_id, award_number, total_obligated_cents,
               fringe_rate_bps=TEST_DEFAULTS["FRINGE_RATE_BPS"], **overrides):
    """Create an award in PENDING_SETUP (PRD §3.1)."""
    payload = create_award_payload(
        sponsor_id, pi_id, award_number=award_number,
        total_obligated_cents=total_obligated_cents,
        fringe_rate_bps=fringe_rate_bps, **overrides)
    return get_success_data(api_client.create_award(payload, SPO))


def make_budget_line(award_id, category, authorized_cents, **overrides):
    payload = create_budget_line_payload(
        award_id, category=category, authorized_cents=authorized_cents, **overrides)
    return get_success_data(api_client.create_budget_line(payload, GC))


def get_award_version(award_id):
    return get_success_data(api_client.get_award(award_id, GA))["version"]


# ---------------------------------------------------------------------------
# Tier 1: award state progression
# ---------------------------------------------------------------------------

def create_active_award(sponsor_id, pi_id, award_number, lines,
                        total_obligated_cents,
                        fringe_rate_bps=TEST_DEFAULTS["FRINGE_RATE_BPS"],
                        **award_overrides):
    """Create an award, load the given (category, authorized[, mtdc_eligible])
    direct lines, and activate it. `lines` items are dicts with keys
    category / authorized_cents / optional mtdc_eligible_cents.

    Returns (award, lines_by_category) where lines_by_category maps
    category -> BudgetLine (first line of that category).
    """
    award = make_award(sponsor_id, pi_id, award_number, total_obligated_cents,
                       fringe_rate_bps=fringe_rate_bps, **award_overrides)
    lines_by_category = {}
    for spec in lines:
        kwargs = {}
        if "mtdc_eligible_cents" in spec:
            kwargs["mtdc_eligible_cents"] = spec["mtdc_eligible_cents"]
        line = make_budget_line(award["id"], spec["category"],
                                spec["authorized_cents"], **kwargs)
        lines_by_category.setdefault(spec["category"], line)
    award = get_success_data(api_client.activate_award(award["id"], SPO))
    return award, lines_by_category


def setup_sponsor_pi(name="NSF-LOC", payment_method="LETTER_OF_CREDIT", **sp_overrides):
    """Sponsor + one PI person. Returns (sponsor, pi)."""
    sponsor = make_sponsor(payment_method=payment_method, name=name, **sp_overrides)
    pi = make_person()
    return sponsor, pi


# ---------------------------------------------------------------------------
# Tier 2: expenditure helpers
# ---------------------------------------------------------------------------

def post_expenditure(award_id, budget_line_id, expenditure_type="TRAVEL",
                     amount_cents=100_000, transaction_date="2026-03-01T00:00:00Z",
                     **overrides):
    """Create + post a non-salary expenditure. Returns the POSTED expenditure."""
    exp = get_success_data(api_client.create_expenditure(
        create_expenditure_payload(
            award_id, budget_line_id, expenditure_type=expenditure_type,
            amount_cents=amount_cents, transaction_date=transaction_date, **overrides),
        GC))
    return get_success_data(api_client.post_expenditure(exp["id"], GA))


def post_salary_expenditure(award_id, salary_line_id, person_id, effort_pct,
                            period_months, transaction_date, **overrides):
    """Create + post a SALARY expenditure (amount computed server-side per the
    PRD §3.2 salary charge rule). Returns the POSTED expenditure."""
    exp = get_success_data(api_client.create_expenditure(
        create_salary_expenditure_payload(
            award_id, salary_line_id, person_id, effort_pct=effort_pct,
            period_months=period_months, transaction_date=transaction_date, **overrides),
        GC))
    return get_success_data(api_client.post_expenditure(exp["id"], GA))


def make_commitment(award_id, person_id, committed_effort_pct=50.0,
                    is_key_personnel=False):
    return get_success_data(api_client.create_effort_commitment(
        create_effort_commitment_payload(
            award_id, person_id, committed_effort_pct=committed_effort_pct,
            is_key_personnel=is_key_personnel), GC))


# ---------------------------------------------------------------------------
# Tier 2b: effort cycle helpers
# ---------------------------------------------------------------------------

def make_cycle(cycle_code="2026-H1", period_start="2026-01-01T00:00:00Z",
               period_end="2026-07-01T00:00:00Z", cycle_months=6):
    return get_success_data(api_client.create_effort_cycle(
        create_effort_cycle_payload(
            cycle_code=cycle_code, period_start=period_start,
            period_end=period_end, cycle_months=cycle_months), GA))


def open_cycle(cycle_id):
    return get_success_data(api_client.open_effort_cycle(cycle_id, GA))


def find_award_statement(cycle_id, award_id):
    """The single AWARD statement for (cycle, award)."""
    data = get_success_data(api_client.list_effort_statements(
        GA, params={"cycle_id": cycle_id, "award_id": award_id}))
    rows = data if isinstance(data, list) else data.get("data", data)
    return rows[0]


def find_nonsponsored_statement(cycle_id, person_id):
    """The single NON_SPONSORED statement for (cycle, person)."""
    data = get_success_data(api_client.list_effort_statements(
        GA, params={"cycle_id": cycle_id, "person_id": person_id,
                    "statement_kind": "NON_SPONSORED"}))
    rows = data if isinstance(data, list) else data.get("data", data)
    return rows[0]


def certify_statement(statement, certified_effort_pct, person_id,
                      role="PrincipalInvestigator", payroll_adjustment_note=None):
    """Certify `statement` as the entity-backed person (PRD §2.1 ownership)."""
    payload = {
        "certified_effort_pct": certified_effort_pct,
        "expected_effort_statement_version": statement["version"],
    }
    if payroll_adjustment_note is not None:
        payload["payroll_adjustment_note"] = payroll_adjustment_note
    headers = (make_pi_headers(person_id) if role == "PrincipalInvestigator"
               else make_research_staff_headers(person_id))
    return api_client.certify_effort_statement(statement["id"], payload, headers)


# ---------------------------------------------------------------------------
# Tier 3: award with spend / draw pool
# ---------------------------------------------------------------------------

def setup_loc_award_with_cash_pool(award_number, lines, total_obligated_cents,
                                   postings, sponsor_name="NSF-LOC",
                                   sponsor_overrides=None):
    """LOC award, ACTIVE, with the given non-salary postings already POSTED.

    postings: list of dicts {category, amount_cents, cash_disbursed,
    transaction_date?}. Each category must have a loaded line.

    Returns (sponsor, pi, award, lines_by_category, posted_expenditures).
    """
    sponsor, pi = setup_sponsor_pi(
        name=sponsor_name, **(sponsor_overrides or {}))
    award, lines = create_active_award(
        sponsor["id"], pi["id"], award_number, lines, total_obligated_cents)
    posted = []
    for p in postings:
        line = lines[p["category"]]
        posted.append(post_expenditure(
            award["id"], line["id"],
            expenditure_type=p.get("expenditure_type", _type_for_category(p["category"])),
            amount_cents=p["amount_cents"],
            cash_disbursed=p.get("cash_disbursed", False),
            transaction_date=p.get("transaction_date", "2026-03-01T00:00:00Z"),
            is_cost_share=p.get("is_cost_share", False)))
    return sponsor, pi, award, lines, posted


_TYPE_FOR_CATEGORY = {
    "TRAVEL": "TRAVEL",
    "EQUIPMENT": "EQUIPMENT",
    "MATERIALS_SUPPLIES": "SUPPLIES",
    "PARTICIPANT_SUPPORT": "PARTICIPANT_SUPPORT",
    "OTHER_DIRECT": "OTHER_DIRECT",
    "PERSONNEL_SALARIES": "SALARY",
}


def _type_for_category(category):
    return _TYPE_FOR_CATEGORY[category]


def create_drawdown(award_id, amount_cents):
    """Create a DRAFT drawdown, reading the award version fresh (OCC, PRD §2.6)."""
    version = get_award_version(award_id)
    return get_success_data(api_client.create_drawdown_request(
        create_drawdown_request_payload(award_id, amount_cents, version), GA))


# ---------------------------------------------------------------------------
# Tier 3b: subaward helpers
# ---------------------------------------------------------------------------

def setup_prime_with_subaward(award_number, sub_line_authorized, sub_mtdc_eligible,
                              other_direct_authorized, total_obligated_cents,
                              subaward_total, risk_rating="LOW",
                              sub_start="2026-01-01T00:00:00Z",
                              sub_end="2026-12-31T00:00:00Z",
                              activate_subaward=True):
    """ACTIVE prime award with SUBAWARDS + OTHER_DIRECT lines, plus a subaward.

    Returns (sponsor, pi, award, lines_by_category, subaward).
    """
    sponsor, pi = setup_sponsor_pi()
    award, lines = create_active_award(
        sponsor["id"], pi["id"], award_number,
        [
            {"category": "SUBAWARDS", "authorized_cents": sub_line_authorized,
             "mtdc_eligible_cents": sub_mtdc_eligible},
            {"category": "OTHER_DIRECT", "authorized_cents": other_direct_authorized},
        ],
        total_obligated_cents)
    subaward = get_success_data(api_client.create_subaward(
        create_subaward_payload(
            award["id"], total_subaward_cents=subaward_total,
            risk_rating=risk_rating, start_date=sub_start, end_date=sub_end),
        SPO))
    if activate_subaward:
        subaward = get_success_data(api_client.activate_subaward(subaward["id"], SPO))
    return sponsor, pi, award, lines, subaward


def record_invoice(subaward_id, invoice_number, period_start, period_end,
                   direct_cents, f_and_a_cents, **overrides):
    return get_success_data(api_client.create_subaward_invoice(
        create_subaward_invoice_payload(
            subaward_id, invoice_number=invoice_number,
            period_start=period_start, period_end=period_end,
            current_period_direct_cents=direct_cents,
            current_period_f_and_a_cents=f_and_a_cents, **overrides), GC))


# ---------------------------------------------------------------------------
# Tier 3c: transfer pair helpers
# ---------------------------------------------------------------------------

def setup_transfer_pair(source_number="S-001", target_number="T-001",
                        source_travel=200_000, target_travel=100_000,
                        source_posted_amount=100_000,
                        source_obligated=300_000, target_obligated=150_000,
                        source_sponsor_name="NSF-LOC"):
    """Two ACTIVE awards under one sponsor; one POSTED TRAVEL expenditure on the
    source award. Returns (sponsor, pi, source_award, source_line, target_award,
    target_line, source_expenditure)."""
    sponsor, pi = setup_sponsor_pi(name=source_sponsor_name)
    aw_s, lines_s = create_active_award(
        sponsor["id"], pi["id"], source_number,
        [{"category": "TRAVEL", "authorized_cents": source_travel}],
        source_obligated)
    aw_t, lines_t = create_active_award(
        sponsor["id"], pi["id"], target_number,
        [{"category": "TRAVEL", "authorized_cents": target_travel}],
        target_obligated)
    expenditure = post_expenditure(
        aw_s["id"], lines_s["TRAVEL"]["id"], amount_cents=source_posted_amount,
        cash_disbursed=True)
    return sponsor, pi, aw_s, lines_s["TRAVEL"], aw_t, lines_t["TRAVEL"], expenditure


def create_submitted_transfer(source_expenditure, target_award, target_line,
                              user_headers=None, justification=None,
                              enhanced_justification=None):
    """Create + submit a cost transfer; returns the SUBMITTED transfer."""
    headers = user_headers or GC
    payload_kwargs = {}
    if justification is not None:
        payload_kwargs["justification"] = justification
    transfer = get_success_data(api_client.create_cost_transfer(
        create_cost_transfer_payload(
            source_expenditure["id"], target_award["id"], target_line["id"],
            **payload_kwargs),
        headers))
    submit_payload = {}
    if enhanced_justification is not None:
        submit_payload["enhanced_justification"] = enhanced_justification
    return get_success_data(api_client.submit_cost_transfer(
        transfer["id"], submit_payload, headers))


# ---------------------------------------------------------------------------
# Tier 4: salary / effort scenarios
# ---------------------------------------------------------------------------

def setup_salary_award(award_number, ibs=24_000_000, appointment_months=12,
                       person_role="PRINCIPAL_INVESTIGATOR",
                       salary_line=1_000_000, fringe_line=300_000,
                       obligated=1_950_000, fringe_rate_bps=3000,
                       committed_effort_pct=50.0, is_key_personnel=True,
                       sponsor_cap=20_000_000,
                       person_name="P. Alpha"):
    """ACTIVE award with PERSONNEL_SALARIES + FRINGE_BENEFITS lines, one person
    with an effort commitment. Returns (sponsor, pi_person_placeholder,
    person, award, sal_line, fringe_line).

    Note: the committed person IS the award PI when person_role is
    PRINCIPAL_INVESTIGATOR (pi_id == person.id), so PI certification is
    ownership-clean.
    """
    sponsor = make_sponsor(salary_cap_annual_cents=sponsor_cap)
    person = make_person(role_type=person_role, ibs=ibs,
                         appointment_months=appointment_months,
                         full_name=person_name)
    award, lines = create_active_award(
        sponsor["id"], person["id"], award_number,
        [
            {"category": "PERSONNEL_SALARIES", "authorized_cents": salary_line},
            {"category": "FRINGE_BENEFITS", "authorized_cents": fringe_line},
        ],
        obligated, fringe_rate_bps=fringe_rate_bps)
    make_commitment(award["id"], person["id"],
                    committed_effort_pct=committed_effort_pct,
                    is_key_personnel=is_key_personnel)
    return sponsor, person, award, lines["PERSONNEL_SALARIES"], lines["FRINGE_BENEFITS"]


def setup_certifying_cycle_with_award_statement(award, person, cycle_code="2026-H1"):
    """Open a CERTIFYING cycle and return (cycle, award_statement).

    The cycle window [2026-01-01, 2026-07-01) covers first-half salary postings.
    """
    cycle = open_cycle(make_cycle(cycle_code=cycle_code)["id"])
    statement = find_award_statement(cycle["id"], award["id"])
    return cycle, statement


# ---------------------------------------------------------------------------
# Tier 5: closeout / FFR helpers
# ---------------------------------------------------------------------------

def setup_closeout_pending_award(award_number="CL-001", obligated=150_000,
                                 clock="2027-01-01T00:00:00Z"):
    """ACTIVE award (TRAVEL 100000) moved to CLOSEOUT_PENDING; the DRAFT FFR
    auto-created by initiate-closeout (PRD §3.9). Returns (sponsor, pi, award,
    line, ffr)."""
    sponsor, pi = setup_sponsor_pi()
    award, lines = create_active_award(
        sponsor["id"], pi["id"], award_number,
        [{"category": "TRAVEL", "authorized_cents": 100_000}],
        obligated)
    get_success_data(api_client.set_clock({"to_iso8601": clock}, ADMIN))
    award = get_success_data(api_client.initiate_closeout(award["id"], GA))
    ffr_rows = get_success_data(api_client.list_final_financial_reports(
        GA, params={"award_id": award["id"]}))
    ffr = ffr_rows[0]
    return sponsor, pi, award, lines["TRAVEL"], ffr
