"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a setup failure
produces a clear "Setup step failed" error instead of a confusing assertion.

Identity threading: Claimant and Employer are entity-backed roles, so every
ownership-gated call uses make_claimant_headers(claimant["id"]) /
make_employer_headers(employer["id"]) with the real entity id — never the
TEST_USERS fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_employer_payload, create_claimant_payload, create_wage_record_payload,
    create_claim_payload, create_determination_payload,
    create_weekly_certification_payload, create_work_search_contact_payload,
    create_overpayment_payload, create_recovery_payload, create_appeal_payload,
    create_extension_program_payload,
)
from .test_users import (
    TEST_USERS, make_claimant_headers, make_employer_headers, make_adjudicator_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
ADJ = TEST_USERS["adjudicator_headers"]
BPO = TEST_USERS["benefit_payment_officer_headers"]
CLERK = TEST_USERS["appeals_clerk_headers"]
REF = TEST_USERS["referee_headers"]


# ─── Tier 0: Primitive creators ─────────────────────────────────────────────

def create_employer(**overrides) -> dict:
    return get_success_data(api_client.create_employer(
        create_employer_payload(**overrides), ADMIN))


def create_claimant(**overrides) -> dict:
    return get_success_data(api_client.create_claimant(
        create_claimant_payload(**overrides), ADMIN))


def add_wage_record(claimant_id, employer_id, quarter, cents, **overrides) -> dict:
    return get_success_data(api_client.create_wage_record(
        create_wage_record_payload(claimant_id, employer_id, quarter, cents, **overrides),
        ADMIN))


def set_clock(iso_instant: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso_instant}, ADMIN))


def set_claim_balance(claim_id, balance_cents):
    return get_success_data(api_client.set_claim_balance(
        {"claim_id": claim_id, "remaining_balance_cents": balance_cents}, ADMIN))


# ─── Tier 1: Claim state progression ────────────────────────────────────────

def create_draft_claim(claimant_id, filed_date="2026-04-05", **overrides) -> dict:
    """Open a DRAFT claim as the owning claimant."""
    return get_success_data(api_client.create_claim(
        create_claim_payload(claimant_id, filed_date, **overrides),
        make_claimant_headers(claimant_id)))


def submit_claim(claim_id, claimant_id) -> dict:
    """DRAFT -> MONETARY_PENDING, acting as the owning claimant."""
    return get_success_data(api_client.submit_claim(
        claim_id, {}, make_claimant_headers(claimant_id)))


def issue_monetary_determination(claim_id, adjudicator_id=None) -> dict:
    """Issue a MONETARY determination. If adjudicator_id is given, that operator
    id is stamped as issuing_adjudicator_id (for segregation-of-duties setups)."""
    headers = make_adjudicator_headers(adjudicator_id) if adjudicator_id else ADJ
    return get_success_data(api_client.create_determination(
        create_determination_payload(claim_id, "MONETARY"), headers))


# Canonical wage profiles used across many design instances.
STANDARD_WAGES = [
    ("2025-Q4", 780000), ("2025-Q3", 360000),
    ("2025-Q2", 360000), ("2025-Q1", 300000),
]
# Single quarter that qualifies at the minimum (hq 130000, total 130000 fails
# the >=260000 floor); used where a claim should be DENIED with one record, or
# (with set_claim_balance) where monetary detail is irrelevant.
TINY_WAGES = [("2025-Q1", 5000)]


def make_eligible_claim(wages=None, filed_date="2026-04-05", emp_overrides=None,
                        clmt_overrides=None):
    """Register one employer + one claimant, file `wages`, then submit and issue a
    MONETARY determination so the claim reaches MONETARILY_ELIGIBLE.

    Returns dict: {employer, claimant, claim, determination}.
    `wages` is a list of (calendar_quarter, gross_wages_cents) tuples; defaults to
    the STANDARD profile (WBA 30000, MBA 780000).
    """
    wages = STANDARD_WAGES if wages is None else wages
    employer = create_employer(**(emp_overrides or {}))
    claimant = create_claimant(**(clmt_overrides or {}))
    for quarter, cents in wages:
        add_wage_record(claimant["id"], employer["id"], quarter, cents)
    claim = create_draft_claim(claimant["id"], filed_date)
    submit_claim(claim["id"], claimant["id"])
    det = issue_monetary_determination(claim["id"])
    claim = get_success_data(api_client.get_claim(claim["id"], ADJ))
    return {"employer": employer, "claimant": claimant, "claim": claim,
            "determination": det}


# ─── Tier 2: Weekly certification lifecycle ─────────────────────────────────

def file_week(claim_id, claimant_id, week_ending_date="2026-04-11", **overrides) -> dict:
    """File a WeeklyCertification (PENDING/UNPAID) as the owning claimant."""
    return get_success_data(api_client.create_weekly_certification(
        create_weekly_certification_payload(claim_id, week_ending_date, **overrides),
        make_claimant_headers(claimant_id)))


def adjudicate_week(wc_id, decision="ELIGIBLE") -> dict:
    return get_success_data(api_client.adjudicate_weekly_certification(
        wc_id, {"decision": decision}, ADJ))


def hold_week(wc_id) -> dict:
    return get_success_data(api_client.hold_weekly_certification(wc_id, {}, ADJ))


def pay_week(wc_id) -> dict:
    return get_success_data(api_client.pay_weekly_certification(wc_id, {}, BPO))


def add_work_search_contact(wc_id, claimant_id, employer_id=None,
                            contact_type="EMPLOYER_APPLICATION",
                            contact_date="2026-04-08") -> dict:
    payload = create_work_search_contact_payload(contact_type, contact_date)
    if employer_id is not None:
        payload["employer_id"] = employer_id
    return get_success_data(api_client.create_work_search_contact(
        wc_id, payload, make_claimant_headers(claimant_id)))


def make_eligible_week(scenario=None, week_ending_date="2026-04-11",
                       reported_earnings_cents=None, work_search_waived=True):
    """On a MONETARILY_ELIGIBLE claim, file a week and adjudicate it ELIGIBLE.

    `scenario` is the dict from make_eligible_claim(); if None a default STANDARD
    eligible claim is created first. Returns (scenario, weekly_certification).
    """
    if scenario is None:
        scenario = make_eligible_claim()
    overrides = {"work_search_waived": work_search_waived}
    if reported_earnings_cents is not None:
        overrides["reported_earnings_cents"] = reported_earnings_cents
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   week_ending_date, **overrides)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    return scenario, wc


def make_paid_week(scenario=None, week_ending_date="2026-04-11",
                   reported_earnings_cents=None, work_search_waived=True):
    """File + adjudicate ELIGIBLE + pay a week. Returns (scenario, weekly_cert)
    with the certification re-fetched after payment."""
    scenario, wc = make_eligible_week(scenario, week_ending_date,
                                      reported_earnings_cents, work_search_waived)
    pay_week(wc["id"])
    wc = get_success_data(api_client.get_weekly_certification(wc["id"], BPO))
    return scenario, wc


# ─── Tier 3: Two-employer base period (for charge-allocation instances) ──────

def make_two_employer_eligible_claim(filed_date="2026-04-05"):
    """ALTERNATE-qualifying claim D with two base-period employers:
      X reported 2026-Q1=300000 ; Y reported Q4=130000, Q3=60000, Q2=50000.
    Reserves seeded at 100000000 each. Returns dict with employer_x, employer_y,
    claimant, claim, determination."""
    emp_x = create_employer(experience_rate=0.02)
    emp_y = create_employer(experience_rate=0.05)
    claimant = create_claimant()
    add_wage_record(claimant["id"], emp_x["id"], "2026-Q1", 300000)
    add_wage_record(claimant["id"], emp_y["id"], "2025-Q4", 130000)
    add_wage_record(claimant["id"], emp_y["id"], "2025-Q3", 60000)
    add_wage_record(claimant["id"], emp_y["id"], "2025-Q2", 50000)
    claim = create_draft_claim(claimant["id"], filed_date)
    submit_claim(claim["id"], claimant["id"])
    det = issue_monetary_determination(claim["id"])
    claim = get_success_data(api_client.get_claim(claim["id"], ADJ))
    return {"employer_x": emp_x, "employer_y": emp_y, "claimant": claimant,
            "claim": claim, "determination": det}


def get_charge_for_employer(employer_id, charge_index=0):
    """Fetch the first EmployerCharge belonging to an employer (after a paid week)."""
    data, _ = _list(api_client.list_employer_charges(employer_id, ADJ))
    assert data, f"expected at least one charge for employer {employer_id}"
    return data[charge_index]


def _list(response):
    """Helper to unwrap a paginated list response in fixtures."""
    body = get_success_data_list(response)
    return body


def get_success_data_list(response):
    """Lenient list unwrap: returns (data_list, meta)."""
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup list step failed with HTTP {response.status_code}: {response.text}")
    body = response.json()
    return body["data"], body["meta"]


# ─── Tier 4: Overpayment lifecycle ──────────────────────────────────────────

def establish_overpayment(claim_id, cause="NONFRAUD", principal_cents=30000) -> dict:
    """Create an ESTABLISHED overpayment. Returns the overpayment (carrying its
    current version for the mandatory OCC field on recoveries)."""
    return get_success_data(api_client.create_overpayment(
        create_overpayment_payload(claim_id, cause, principal_cents), ADJ))


def make_overpayment(cause="NONFRAUD", principal_cents=30000, filed_date="2026-04-05"):
    """Minimal claim (one tiny wage record, DRAFT claim) + an ESTABLISHED
    overpayment against it. Overpayment establishment does not require an eligible
    claim. Returns dict: {employer, claimant, claim, overpayment}."""
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q1", 5000)
    claim = create_draft_claim(claimant["id"], filed_date)
    op = establish_overpayment(claim["id"], cause, principal_cents)
    return {"employer": employer, "claimant": claimant, "claim": claim,
            "overpayment": op}


def apply_recovery(overpayment_id, amount_cents, expected_version,
                   recovery_method="CASH", weekly_certification_id=None) -> dict:
    payload = create_recovery_payload(recovery_method, amount_cents, expected_version)
    if weekly_certification_id is not None:
        payload["weekly_certification_id"] = weekly_certification_id
    return get_success_data(api_client.create_recovery(overpayment_id, payload, BPO))


def current_overpayment_version(overpayment_id) -> int:
    op = get_success_data(api_client.get_overpayment(overpayment_id, BPO))
    return op["version"]


# ─── Tier 5: Appeal lifecycle ───────────────────────────────────────────────

def make_denied_determination(adjudicator_id="adj-default",
                              filed_date="2026-04-05", det_clock="2026-04-10T00:00:00Z"):
    """A claim that fails monetary qualification (single tiny wage record) so the
    MONETARY determination is DENIED and the claim is MONETARILY_INELIGIBLE.
    Sets the server clock first so appeal_deadline_date is deterministic.
    Returns dict: {employer, claimant, claim, determination}."""
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q1", 5000)
    claim = create_draft_claim(claimant["id"], filed_date)
    submit_claim(claim["id"], claimant["id"])
    if det_clock:
        set_clock(det_clock)
    det = issue_monetary_determination(claim["id"], adjudicator_id=adjudicator_id)
    claim = get_success_data(api_client.get_claim(claim["id"], ADJ))
    return {"employer": employer, "claimant": claimant, "claim": claim,
            "determination": det}


def file_appeal(determination_id, claimant_id, filed_by="CLAIMANT",
                filed_date="2026-04-20") -> dict:
    return get_success_data(api_client.create_appeal(
        create_appeal_payload(determination_id, filed_by, filed_date),
        make_claimant_headers(claimant_id)))


def assign_referee(appeal_id, referee_id="ref-1") -> dict:
    return get_success_data(api_client.assign_appeal(
        appeal_id, {"assigned_referee_id": referee_id}, CLERK))


def make_appeal_under_review(adjudicator_id="adj-default", referee_id="ref-1",
                             filed_date="2026-04-05", appeal_filed_date="2026-04-20"):
    """A DENIED MONETARY determination, an appeal SUBMITTED then assigned a referee
    (UNDER_REVIEW). Returns dict adding `appeal`."""
    scenario = make_denied_determination(adjudicator_id=adjudicator_id,
                                         filed_date=filed_date)
    appeal = file_appeal(scenario["determination"]["id"], scenario["claimant"]["id"],
                         filed_date=appeal_filed_date)
    appeal = assign_referee(appeal["id"], referee_id)
    scenario["appeal"] = appeal
    return scenario


def remand_appeal(appeal_id) -> dict:
    return get_success_data(api_client.remand_appeal(appeal_id, {}, REF))


def decide_appeal(appeal_id, ruling) -> dict:
    return get_success_data(api_client.decide_appeal(appeal_id, {"ruling": ruling}, REF))


# ─── Tier 6: Extension program ──────────────────────────────────────────────

def create_extension_program(extra_weeks=13, trigger_start_date="2026-01-01",
                             trigger_end_date="2026-12-31", **overrides) -> dict:
    return get_success_data(api_client.create_extension_program(
        create_extension_program_payload(extra_weeks, trigger_start_date,
                                         trigger_end_date, **overrides),
        ADMIN))


def make_exhausted_claim(wages=None, filed_date="2026-04-05", forced_balance=5000):
    """Drive a claim to EXHAUSTED: build an eligible claim, force its balance to
    `forced_balance` via the test hook, then file/adjudicate/pay one final week
    that consumes the balance exactly to 0. Returns (scenario, paid_week).

    Defaults to a two-quarter profile (Q4+Q3 each 130000) that qualifies under PRD
    §3.2 (total 260000 >= 260000 floor; hq 130000; 2*total >= 3*hq) so the high
    quarter 130000 -> WBA 5000 and base MBA min(5000*26, floor(0.5*260000)) =
    130000. A forced balance of 5000 is then paid in full, driving the claim to
    EXHAUSTED. (A single quarter of 130000 fails the >=260000 base-period floor and
    would never reach MONETARILY_ELIGIBLE.)
    """
    wages = [("2025-Q4", 130000), ("2025-Q3", 130000)] if wages is None else wages
    scenario = make_eligible_claim(wages=wages, filed_date=filed_date)
    set_claim_balance(scenario["claim"]["id"], forced_balance)
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", reported_earnings_cents=0, work_search_waived=True)
    wc = adjudicate_week(wc["id"], "ELIGIBLE")
    pay_week(wc["id"])
    scenario["claim"] = get_success_data(
        api_client.get_claim(scenario["claim"]["id"], ADJ))
    scenario["paid_week"] = get_success_data(
        api_client.get_weekly_certification(wc["id"], BPO))
    return scenario
