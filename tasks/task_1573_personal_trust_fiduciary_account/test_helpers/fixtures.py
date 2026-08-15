"""Composite setup helpers for the fiduciary trust domain.

Every fixture builds its preconditions from scratch via the public API
(the harness restarts the server before every test). Setup calls use the
lenient get_success_data() so failures surface as clear "Setup failed"
errors instead of confusing assertion failures.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_beneficiary_payload,
    create_committee_member_payload,
    create_distribution_request_payload,
    create_document_payload,
    create_fee_assessment_payload,
    create_holding_payload,
    create_ips_payload,
    create_ledger_entry_payload,
    create_tax_filing_payload,
    create_trust_payload,
)
from .test_users import (
    TEST_USERS,
    make_beneficiary_headers,
    make_committee_member_headers,
    make_executive_headers,
    make_ops_headers,
)

OFFICER = TEST_USERS["officer_headers"]
EXEC = TEST_USERS["executive_headers"]
MANAGER = TEST_USERS["manager_headers"]
OPS = TEST_USERS["ops_headers"]
TAX = TEST_USERS["tax_headers"]


def _setup_ok(resp, what: str):
    assert resp.status_code < 300, (
        f"Setup failed ({what}): HTTP {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_trust(**overrides) -> dict:
    """Create a trust account in DRAFT. Returns the TrustAccount."""
    resp = api_client.create_trust(create_trust_payload(**overrides), OFFICER)
    _setup_ok(resp, "create trust")
    return get_success_data(resp)


def create_active_trust(
    with_document: bool = True,
    beneficiaries: Optional[List[dict]] = None,
    document_per_stirpes: bool = False,
    **trust_overrides,
) -> dict:
    """Create a trust, optionally enroll beneficiaries first, move it
    DRAFT -> UNDER_ACCEPTANCE_REVIEW -> ACTIVE.

    Acceptance requires an APPROVED TrustDocument (PRD §3.1: "at least one
    TrustDocument of the trust must be APPROVED, otherwise
    ERR_DOCUMENT_NOT_APPROVED"), so by default one is created
    (submit -> interpret -> approve) before acceptance. Beneficiaries given
    as factory overrides are created before acceptance so the 10000-bps
    class precondition can be satisfied.
    """
    trust = create_trust(**trust_overrides)
    if with_document:
        create_approved_document(trust["id"], per_stirpes=document_per_stirpes)
    for ben in beneficiaries or []:
        add_beneficiary(trust["id"], **ben)
    resp = api_client.submit_for_acceptance(trust["id"], OFFICER)
    _setup_ok(resp, "submit-for-acceptance")
    resp = api_client.accept_trust(trust["id"], EXEC)
    _setup_ok(resp, "accept trust")
    return get_success_data(resp)


def create_approved_document(trust_id: str, per_stirpes: bool = False,
                             version_number: int = 1, **overrides) -> dict:
    """Create a TrustDocument and walk DRAFT -> SUBMITTED -> INTERPRETED ->
    APPROVED. Returns the APPROVED document."""
    resp = api_client.create_document(
        create_document_payload(trust_id=trust_id, version_number=version_number, **overrides),
        OFFICER,
    )
    _setup_ok(resp, "create document")
    doc = get_success_data(resp)
    _setup_ok(api_client.submit_document(doc["id"], OFFICER), "submit document")
    _setup_ok(
        api_client.interpret_document(
            doc["id"],
            {"per_stirpes": per_stirpes, "interpretation_notes": "interpreted"},
            OFFICER,
        ),
        "interpret document",
    )
    resp = api_client.approve_document(doc["id"], EXEC)
    _setup_ok(resp, "approve document")
    return get_success_data(resp)


def add_beneficiary(trust_id: str, **overrides) -> dict:
    resp = api_client.create_beneficiary(
        create_beneficiary_payload(trust_id=trust_id, **overrides), OFFICER
    )
    _setup_ok(resp, "add beneficiary")
    return get_success_data(resp)


def add_committee_members(count: int, name_prefix: str = "CM") -> List[dict]:
    """Create `count` ACTIVE committee members. Returns them in creation order."""
    members = []
    for i in range(count):
        resp = api_client.create_committee_member(
            create_committee_member_payload(full_name=f"{name_prefix} {i + 1}"), EXEC
        )
        _setup_ok(resp, "create committee member")
        members.append(get_success_data(resp))
    return members


def post_receipt(trust_id: str, amount_cents: int, receipt_type: str = "INTEREST",
                 value_date: str = "2026-08-06", description: str = "receipt") -> list:
    """Post a manual RECEIPT; returns the appended LedgerEntry rows (1 or 2)."""
    resp = api_client.create_ledger_entry(
        create_ledger_entry_payload(
            trust_id=trust_id,
            amount_cents=amount_cents,
            receipt_type=receipt_type,
            value_date=value_date,
            description=description,
        ),
        OPS,
    )
    _setup_ok(resp, f"post {receipt_type} receipt")
    return get_success_data(resp)


def post_adjustment(trust_id: str, bucket: str, amount_cents: int,
                    value_date: str = "2026-08-20", description: str = "adjustment") -> list:
    """Post a manual ADJUSTMENT with an explicit bucket."""
    resp = api_client.create_ledger_entry(
        {
            "trust_id": trust_id,
            "entry_kind": "ADJUSTMENT",
            "bucket": bucket,
            "amount_cents": amount_cents,
            "value_date": value_date,
            "description": description,
        },
        OPS,
    )
    _setup_ok(resp, "post adjustment")
    return get_success_data(resp)


def trust_version(trust_id: str, headers=None) -> int:
    """Current TrustAccount.version (the OCC pivot, PRD §2.7)."""
    resp = api_client.get_trust(trust_id, headers or OFFICER)
    _setup_ok(resp, "read trust version")
    return get_success_data(resp)["version"]


def get_trust(trust_id: str, headers=None) -> dict:
    resp = api_client.get_trust(trust_id, headers or OFFICER)
    _setup_ok(resp, "read trust")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — funded trusts with committee and beneficiaries
# ---------------------------------------------------------------------------

def setup_funded_trust(
    income_cents: int = 0,
    principal_cents: int = 0,
    committee_size: int = 0,
    income_beneficiaries: Optional[List[dict]] = None,
    all_beneficiaries: Optional[List[dict]] = None,
    with_document: bool = True,
    **trust_overrides,
) -> dict:
    """ACTIVE trust with optional committee, beneficiaries, and posted
    INTEREST (income) / INITIAL_FUNDING (principal) receipts.

    Returns {"trust", "members", "beneficiaries"} where beneficiaries is a
    list of created Beneficiary rows.
    """
    ben_overrides = list(all_beneficiaries or []) + [
        {"beneficiary_class": "INCOME", **b} for b in (income_beneficiaries or [])
    ]
    if not ben_overrides and committee_size:
        # voting scenarios usually want a beneficiary to file for
        ben_overrides = [{"full_name": "Ivy Inc"}]
    trust = create_active_trust(
        with_document=with_document, beneficiaries=ben_overrides, **trust_overrides
    )
    members = add_committee_members(committee_size) if committee_size else []
    created_bens = []
    if ben_overrides:
        resp = api_client.list_beneficiaries(OFFICER, params={"trust_id": trust["id"]})
        _setup_ok(resp, "list beneficiaries")
        created_bens = get_success_data(resp)
    if principal_cents:
        post_receipt(trust["id"], principal_cents, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="principal funding")
    if income_cents:
        post_receipt(trust["id"], income_cents, receipt_type="INTEREST",
                     value_date="2026-08-06", description="income")
    trust = get_trust(trust["id"])
    return {"trust": trust, "members": members, "beneficiaries": created_bens}


# ---------------------------------------------------------------------------
# Tier 3: distribution-request lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_request(trust_id: str, beneficiary_id: str, amount_cents: int = 1000000,
                   as_beneficiary: bool = False, **overrides) -> dict:
    """Create a SUBMITTED DistributionRequest, threading the current trust
    version into the OCC field. Returns the created request."""
    payload = create_distribution_request_payload(
        trust_id=trust_id,
        beneficiary_id=beneficiary_id,
        amount_cents=amount_cents,
        expected_trust_account_version=trust_version(trust_id),
        **overrides,
    )
    headers = make_beneficiary_headers(beneficiary_id) if as_beneficiary else OFFICER
    resp = api_client.create_distribution_request(payload, headers)
    _setup_ok(resp, "create distribution request")
    return get_success_data(resp)


def create_request_in_review(trust_id: str, beneficiary_id: str,
                             amount_cents: int = 1000000, **overrides) -> dict:
    req = create_request(trust_id, beneficiary_id, amount_cents, **overrides)
    _setup_ok(api_client.start_review(req["id"], OFFICER), "start-review")
    return get_success_data(api_client.get_distribution_request(req["id"], OFFICER))


def create_request_in_voting(trust_id: str, beneficiary_id: str,
                             amount_cents: int = 1000000, **overrides) -> dict:
    """SUBMITTED -> UNDER_REVIEW -> VOTING. Reservation is applied."""
    req = create_request_in_review(trust_id, beneficiary_id, amount_cents, **overrides)
    resp = api_client.open_voting(req["id"], OFFICER)
    _setup_ok(resp, "open-voting")
    return get_success_data(resp)


def cast_votes(request_id: str, member_ids: List[str], vote: str = "APPROVE") -> None:
    for mid in member_ids:
        resp = api_client.cast_vote(
            request_id, {"vote": vote}, make_committee_member_headers(mid)
        )
        _setup_ok(resp, f"cast {vote} vote")


def create_approved_request(trust_id: str, beneficiary_id: str, member_ids: List[str],
                            amount_cents: int = 1000000, **overrides) -> dict:
    """Request walked to APPROVED with exactly 3 APPROVE votes."""
    req = create_request_in_voting(trust_id, beneficiary_id, amount_cents, **overrides)
    cast_votes(req["id"], member_ids[:3], "APPROVE")
    resp = api_client.get_distribution_request(req["id"], OFFICER)
    _setup_ok(resp, "read approved request")
    return get_success_data(resp)


def create_disbursed_request(trust_id: str, beneficiary_id: str, member_ids: List[str],
                             amount_cents: int = 1000000, **overrides) -> dict:
    """Request walked APPROVED -> DISBURSED (ledger rows appended)."""
    req = create_approved_request(trust_id, beneficiary_id, member_ids, amount_cents, **overrides)
    resp = api_client.disburse_request(req["id"], OPS)
    _setup_ok(resp, "disburse request")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: holdings / IPS / compliance
# ---------------------------------------------------------------------------

def setup_active_ips(trust_id: str, **overrides) -> dict:
    """Create an IPS and activate it (runs the immediate drift check)."""
    resp = api_client.create_ips(create_ips_payload(trust_id=trust_id, **overrides), MANAGER)
    _setup_ok(resp, "create IPS")
    ips = get_success_data(resp)
    resp = api_client.activate_ips(ips["id"], MANAGER)
    _setup_ok(resp, "activate IPS")
    return get_success_data(resp)


def buy_holding(trust_id: str, asset_class: str, ticker: str, units: int,
                unit_price_cents: int) -> dict:
    """Purchase a holding, threading the current trust version (OCC)."""
    resp = api_client.create_holding(
        create_holding_payload(
            trust_id=trust_id,
            asset_class=asset_class,
            ticker=ticker,
            units=units,
            unit_price_cents=unit_price_cents,
            expected_trust_account_version=trust_version(trust_id, MANAGER),
        ),
        MANAGER,
    )
    _setup_ok(resp, f"buy {ticker}")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Fee assessment lifecycle
# ---------------------------------------------------------------------------

def create_fee(trust_id: str, **overrides) -> dict:
    resp = api_client.create_fee_assessment(
        create_fee_assessment_payload(trust_id=trust_id, **overrides), OPS
    )
    _setup_ok(resp, "create fee assessment")
    return get_success_data(resp)


def create_posted_fee(trust_id: str, discloser: str = "ops_disc",
                      poster: str = "ops_post", **overrides) -> dict:
    """FINAL fee walked CALCULATED -> DISCLOSED -> POSTED with two different
    operations users (segregation of duties, PRD §2.9)."""
    fee = create_fee(trust_id, **overrides)
    _setup_ok(api_client.disclose_fee(fee["id"], make_ops_headers(discloser)), "disclose fee")
    resp = api_client.post_fee(fee["id"], make_ops_headers(poster))
    _setup_ok(resp, "post fee")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tax filings
# ---------------------------------------------------------------------------

def create_filing(trust_id: str, tax_year: int = 2026) -> dict:
    resp = api_client.create_tax_filing(
        create_tax_filing_payload(trust_id=trust_id, tax_year=tax_year), TAX
    )
    _setup_ok(resp, "create tax filing")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: termination gauntlet
# ---------------------------------------------------------------------------

def get_termination_case(trust_id: str) -> dict:
    """The TerminationCase created by terminating `trust_id` (PRD §3.9)."""
    resp = api_client.list_termination_cases(OFFICER, params={"trust_id": trust_id})
    _setup_ok(resp, "list termination cases")
    cases = get_success_data(resp)
    assert cases, "Setup failed: no TerminationCase found after terminate"
    return cases[0]


def terminate_trust(trust_id: str, reason: str = "directed termination",
                    initiator_headers=None) -> dict:
    """ACTIVE -> TERMINATING; returns the created TerminationCase (INITIATED)."""
    resp = api_client.terminate_trust(trust_id, {"reason": reason}, initiator_headers or OFFICER)
    _setup_ok(resp, "terminate trust")
    return get_termination_case(trust_id)


def advance_case_to_final_accounting_approved(
    trust_id: str,
    reserve_taxes_cents: int = 100000,
    reserve_fees_cents: int = 100000,
    initiator_headers=None,
    approver_headers=None,
) -> dict:
    """Terminate an ACTIVE trust and walk the case to
    FINAL_ACCOUNTING_APPROVED (vacuous tax clearance when no filings exist).
    initiator and approver default to two different identities (SoD)."""
    case = terminate_trust(trust_id, initiator_headers=initiator_headers)
    _setup_ok(
        api_client.reserve_liabilities(
            case["id"],
            {"reserve_taxes_cents": reserve_taxes_cents, "reserve_fees_cents": reserve_fees_cents},
            OFFICER,
        ),
        "reserve liabilities",
    )
    _setup_ok(api_client.record_tax_clearance(case["id"], TAX), "record tax clearance")
    resp = api_client.approve_final_accounting(
        case["id"], approver_headers or make_executive_headers("exec_second")
    )
    _setup_ok(resp, "approve final accounting")
    return get_success_data(resp)
