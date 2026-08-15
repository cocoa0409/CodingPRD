"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch through the public API,
because the test harness restarts the server before every test. Setup calls
use the lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
SPEC = TEST_USERS["specialist_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
SUP2 = TEST_USERS["supervisor2_headers"]
ACCT = TEST_USERS["accountant_headers"]
ERO = TEST_USERS["estate_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_member(state_code="CA", medicaid_id=None, full_name=None):
    """Register a member (PRD §3.1). Returns the Member data dict."""
    overrides = {}
    if medicaid_id is not None:
        overrides["medicaid_id"] = medicaid_id
    if full_name is not None:
        overrides["full_name"] = full_name
    resp = api_client.create_member(
        factories.member_payload(state_code=state_code, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_case(member_id, injury_date="2026-01-01", third_party_insurer="InsCo"):
    """Identify a TPL case (PRD §3.2). Returns the TplCase data dict."""
    resp = api_client.create_case(
        factories.case_payload(
            member_id, injury_date=injury_date,
            third_party_insurer=third_party_insurer,
        ),
        SPEC,
    )
    return get_success_data(resp)


def get_case(case_id):
    return get_success_data(api_client.get_case(case_id, SPEC))


def get_case_version(case_id) -> int:
    return get_case(case_id)["version"]


def notify_attorney(case_id):
    return get_success_data(api_client.notify_attorney(case_id, SPEC))


def add_expense_claim(case_id, service_date, paid_amount_cents, claim_reference=None):
    overrides = {}
    if claim_reference is not None:
        overrides["claim_reference"] = claim_reference
    resp = api_client.add_expense_claim(
        case_id,
        factories.expense_claim_payload(
            service_date=service_date,
            paid_amount_cents=paid_amount_cents,
            **overrides,
        ),
        SPEC,
    )
    return get_success_data(resp)


def file_lien(case_id):
    return get_success_data(api_client.file_lien(case_id, SPEC))


def get_lien(lien_id):
    return get_success_data(api_client.get_lien(lien_id, SPEC))


def get_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, SPEC))


def get_posting(posting_id):
    return get_success_data(api_client.get_posting(posting_id, ACCT))


def get_waiver(waiver_id):
    return get_success_data(api_client.get_waiver(waiver_id, SUP1))


def get_estate_case(estate_case_id):
    return get_success_data(api_client.get_estate_case(estate_case_id, ERO))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: case hierarchy — member + case + claims + lien
# ---------------------------------------------------------------------------

def setup_case_with_lien(state_code="CA", injury_date="2026-01-01",
                         claims=None, medicaid_id=None):
    """Member + case + attorney notification + expense claims + filed lien.

    `claims` is a list of (service_date, paid_amount_cents) tuples; the default
    is a single post-injury claim of 200000 cents so the lien perfects at
    200000 (below the statutory cap). Returns a dict with member, case, lien
    and claims keys.
    """
    if claims is None:
        claims = [("2026-01-10", 200000)]
    member = create_member(state_code=state_code, medicaid_id=medicaid_id)
    case = create_case(member["id"], injury_date=injury_date)
    notify_attorney(case["id"])
    claim_rows = [
        add_expense_claim(case["id"], sd, amt, claim_reference=f"CL-{i}-{case['id'][:8]}")
        for i, (sd, amt) in enumerate(claims)
    ]
    lien = file_lien(case["id"])
    return {"member": member, "case": get_case(case["id"]),
            "lien": lien, "claims": claim_rows}


# ---------------------------------------------------------------------------
# Tier 3: negotiation lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_open_settlement(case_id, gross_amount_cents=1000000,
                           attorney_fee_pct=0.25, litigation_costs_cents=100000,
                           offered_by="INSURER", creator="specialist"):
    """Open a negotiation on a LIEN_FILED case (PRD §3.4).

    Reads the case's current version for the OCC guard. `creator` selects the
    operator whose X-User-ID is recorded as created_by_user_id: "specialist"
    (spec_1) or "supervisor" (sup_1).
    """
    headers = SPEC if creator == "specialist" else SUP1
    case_version = get_case_version(case_id)
    resp = api_client.create_settlement(
        case_id,
        factories.settlement_payload(
            case_version,
            gross_amount_cents=gross_amount_cents,
            attorney_fee_pct=attorney_fee_pct,
            litigation_costs_cents=litigation_costs_cents,
            offered_by=offered_by,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_settlement_offered(state_code="CA", injury_date="2026-01-01",
                             claims=None, gross_amount_cents=1000000,
                             attorney_fee_pct=0.25, litigation_costs_cents=100000,
                             offered_by="INSURER", creator="specialist",
                             medicaid_id=None):
    """Case with a filed lien plus an OFFERED settlement (round 1)."""
    ctx = setup_case_with_lien(
        state_code=state_code, injury_date=injury_date, claims=claims,
        medicaid_id=medicaid_id,
    )
    settlement = create_open_settlement(
        ctx["case"]["id"],
        gross_amount_cents=gross_amount_cents,
        attorney_fee_pct=attorney_fee_pct,
        litigation_costs_cents=litigation_costs_cents,
        offered_by=offered_by,
        creator=creator,
    )
    ctx["settlement"] = settlement
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def accept_settlement(settlement_id, headers=None):
    """Accept an OFFERED/COUNTERED settlement as a supervisor (PRD §3.4)."""
    return get_success_data(
        api_client.accept_settlement(settlement_id, headers or SUP1)
    )


def setup_accepted_settlement(posting_amount=None, **kwargs):
    """Settlement driven to ACCEPTED (PRD §3.4).

    The acceptor is always a different operator than the creator so the
    segregation-of-duties gate passes.
    """
    ctx = setup_settlement_offered(**kwargs)
    ctx["settlement"] = accept_settlement(ctx["settlement"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["lien"] = get_lien(ctx["lien"]["id"])
    return ctx


def create_pending_posting(settlement_id, gross_recovery_cents,
                           contractor_code="CTR-A"):
    """Record an insurer check against an ACCEPTED settlement (PRD §3.5)."""
    resp = api_client.create_posting(
        settlement_id,
        factories.posting_payload(
            gross_recovery_cents=gross_recovery_cents,
            contractor_code=contractor_code,
        ),
        ACCT,
    )
    return get_success_data(resp)


def setup_pending_posting(posting_amount=200000, **kwargs):
    """ACCEPTED settlement plus one PENDING posting of `posting_amount` cents."""
    ctx = setup_accepted_settlement(**kwargs)
    posting = create_pending_posting(ctx["settlement"]["id"], posting_amount)
    ctx["posting"] = posting
    return ctx


def setup_posted_recovery(posting_amount=200000, **kwargs):
    """Full TPL lifecycle through POSTED: lien satisfied, case resolved (PRD §3.5)."""
    ctx = setup_pending_posting(posting_amount=posting_amount, **kwargs)
    ctx["posting"] = get_success_data(
        api_client.post_posting(ctx["posting"]["id"], ACCT)
    )
    ctx["lien"] = get_lien(ctx["lien"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["settlement"] = get_settlement(ctx["settlement"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: estate recovery lifecycle
# ---------------------------------------------------------------------------

def mark_member_deceased(member_id, date_of_death="2026-02-01",
                         lifetime_paid_cents=500000):
    """Record a member's death; opens the estate case (PRD §3.6)."""
    resp = api_client.mark_deceased(
        member_id,
        factories.mark_deceased_payload(
            date_of_death=date_of_death, lifetime_paid_cents=lifetime_paid_cents
        ),
        ERO,
    )
    return get_success_data(resp)


def get_estate_case_for_member(member_id):
    """Look up the estate case opened for a member via the list endpoint."""
    resp = api_client.list_estate_cases(ERO, params={"member_id": member_id})
    rows = get_success_data(resp)
    assert len(rows) == 1, f"Expected exactly one estate case for {member_id}"
    return rows[0]


def setup_estate_opened(state_code="CA", date_of_death="2026-02-01",
                        lifetime_paid_cents=500000, medicaid_id=None):
    """Member marked deceased; estate case in OPENED (PRD §3.6)."""
    member = create_member(state_code=state_code, medicaid_id=medicaid_id)
    member = mark_member_deceased(
        member["id"], date_of_death=date_of_death,
        lifetime_paid_cents=lifetime_paid_cents,
    )
    estate_case = get_estate_case_for_member(member["id"])
    return {"member": member, "estate_case": estate_case}


def setup_estate_claim_filed(exempt_services_cents=0, probate_case_number=None,
                             **kwargs):
    """Estate case driven to CLAIM_FILED (PRD §3.6)."""
    ctx = setup_estate_opened(**kwargs)
    overrides = {"exempt_services_cents": exempt_services_cents}
    if probate_case_number is not None:
        overrides["probate_case_number"] = probate_case_number
    estate_case = get_success_data(
        api_client.file_estate_claim(
            ctx["estate_case"]["id"], factories.file_claim_payload(**overrides), ERO
        )
    )
    ctx["estate_case"] = estate_case
    return ctx


def setup_pending_waiver(waiver_type="FULL", household_income_annual_cents=1000000,
                         homestead_value_cents=1000000,
                         requested_reduction_cents=None, filer="ero",
                         **kwargs):
    """Estate CLAIM_FILED plus one PENDING hardship waiver (PRD §3.7).

    `filer` selects the operator recorded as created_by_user_id: "ero" (ero_1)
    or "supervisor" (sup_1).
    """
    ctx = setup_estate_claim_filed(**kwargs)
    payload_overrides = {
        "waiver_type": waiver_type,
        "household_income_annual_cents": household_income_annual_cents,
        "homestead_value_cents": homestead_value_cents,
    }
    if requested_reduction_cents is not None:
        payload_overrides["requested_reduction_cents"] = requested_reduction_cents
    headers = ERO if filer == "ero" else SUP1
    waiver = get_success_data(
        api_client.create_waiver(
            ctx["estate_case"]["id"],
            factories.waiver_payload(**payload_overrides),
            headers,
        )
    )
    ctx["waiver"] = waiver
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: notices
# ---------------------------------------------------------------------------

def list_notices(**filters):
    """List communication notices matching the given filter params (PRD §3.8)."""
    params = {k: v for k, v in filters.items() if v is not None}
    return get_success_data(api_client.list_notices(SPEC, params=params))


def find_notice(notice_type, case_id=None, estate_case_id=None, member_id=None):
    """Return the single notice of `notice_type` for the given parent."""
    rows = list_notices(
        notice_type=notice_type, case_id=case_id,
        estate_case_id=estate_case_id, member_id=member_id,
    )
    assert len(rows) == 1, (
        f"Expected exactly one {notice_type} notice, got {len(rows)}"
    )
    return rows[0]
