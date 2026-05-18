"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests require the system in a late state (e.g., a CD in
READY_TO_FUND on an escrow file in CONTINGENT_WIRE, plus a CONFIRMED
wire to QI). Each fixture composes the lower-level steps so the test
body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

- EscrowOfficer / TitleOfficer / DisbursementApprover are OPAQUE; shared
  constants are canonical. Two distinct EscrowOfficer ids are used
  whenever a fixture must satisfy the SoD rule: the CD issuer must
  differ from whichever operator confirms the wire or approves the
  disbursement (PRD §2.11). Tests that exercise SoD must not collapse
  these two ids.

- Buyer is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Buyer,
  X-User-ID is the id of the acting Party ... a buyer can only
  acknowledge a Closing Disclosure or sign a CC&R disclosure on an
  escrow file whose buyer_party_id equals the caller's X-User-ID."
  Every Buyer-acting call (POST /ccr-disclosures, POST
  /closing-disclosures/{id}/acknowledge) MUST use
  make_buyer_headers(escrow_file["buyer_party_id"]) where the id is the
  actual Party.id minted by POST /parties.

- Seller is ENTITY-BACKED analogously; use
  make_seller_headers(escrow_file["seller_party_id"]). Seller-acting
  calls are read-only, so this matters mostly for tests exercising
  Seller GET access.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    ccr_disclosure_payload,
    closing_disclosure_payload,
    clock_advance_payload,
    confirm_callback_payload,
    cancel_escrow_payload,
    disbursement_payload,
    emd_payload,
    emd_release_payload,
    escrow_file_payload,
    exchange_payload,
    iso_utc,
    parse_iso,
    party_payload,
    property_payload,
    revise_cd_payload,
    title_policy_payload,
    title_search_findings_payload,
    title_search_payload,
    version_only_payload,
    wire_instruction_payload,
    with_idempotency,
)
from .test_users import (
    DISBURSEMENT_APPROVER_ID,
    ESCROW_OFFICER_ID,
    ESCROW_OFFICER_ID_ALT,
    TEST_USERS,
    make_buyer_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.10
# ===========================================================================
def get_clock_now(
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """POST /_clock/now — returns the server clock now field."""
    headers = headers or TEST_USERS["escrow_officer_headers"]
    resp = api_client.clock_now(headers)
    data = get_success_data(resp)
    return data["now"]


def server_now_dt() -> datetime:
    """Return server clock as a UTC datetime."""
    return parse_iso(get_clock_now())


def advance_clock_to(
    to_iso: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.10. EscrowOfficer is the
    role permitted to advance the clock."""
    headers = headers or with_idempotency(
        TEST_USERS["escrow_officer_headers"],
    )
    if "Idempotency-Key" not in headers:
        headers = with_idempotency(headers)
    resp = api_client.advance_clock(
        clock_advance_payload(to_iso), headers,
    )
    return get_success_data(resp)


def advance_clock_by(*, days: int = 0, hours: int = 0,
                     minutes: int = 0, seconds: int = 0) -> Dict[str, Any]:
    """Advance the server clock by a relative offset from server_now."""
    base = server_now_dt()
    target = base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    )
    return advance_clock_to(iso_utc(target))


# ===========================================================================
# Tier 1 — Primitive single-entity setup
# ===========================================================================
def create_party(
    party_kind: str,
    *,
    full_name: Optional[str] = None,
    contact_email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /parties. PRD §3.1 — EscrowOfficer creates parties."""
    headers = headers or with_idempotency(
        TEST_USERS["escrow_officer_headers"],
    )
    if "Idempotency-Key" not in headers:
        headers = with_idempotency(headers)
    payload = party_payload(
        party_kind=party_kind,
        full_name=full_name,
        contact_email=contact_email,
    )
    resp = api_client.create_party(payload, headers)
    return get_success_data(resp)


def create_property_entity(
    *,
    hoa_annual_dues: float = TEST_DEFAULTS["HOA_ANNUAL_DUES"],
    tax_annual: float = TEST_DEFAULTS["TAX_ANNUAL"],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties. PRD §3.1."""
    headers = headers or with_idempotency(
        TEST_USERS["escrow_officer_headers"],
    )
    if "Idempotency-Key" not in headers:
        headers = with_idempotency(headers)
    payload = property_payload(
        hoa_annual_dues=hoa_annual_dues, tax_annual=tax_annual,
    )
    resp = api_client.create_property(payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 2 — Escrow file with parties and property
# ===========================================================================
def create_escrow_file_basic(
    *,
    purchase_price: float = TEST_DEFAULTS["PURCHASE_PRICE"],
    loan_amount: float = TEST_DEFAULTS["LOAN_AMOUNT"],
    hoa_annual_dues: float = TEST_DEFAULTS["HOA_ANNUAL_DUES"],
    tax_annual: float = TEST_DEFAULTS["TAX_ANNUAL"],
    closing_date_planned: str = TEST_DEFAULTS["CLOSING_DATE_PLANNED"],
    is_1031_exchange: bool = False,
    include_lender: bool = True,
    include_qi: bool = False,
) -> Dict[str, Any]:
    """Create buyer, seller, optional lender and QI, property, and
    escrow file. Returns a bundle dict with keys:
        property, buyer, seller, lender, qi, escrow_file

    PRD §3.2: opening a file requires property_id, buyer_party_id,
    seller_party_id, optionally lender_party_id (cash deal omits) and
    qi_party_id (§1031 only).
    """
    eo_headers = TEST_USERS["escrow_officer_headers"]

    buyer = create_party("BUYER")
    seller = create_party("SELLER")
    lender = create_party("LENDER") if include_lender else None
    qi = create_party("QUALIFIED_INTERMEDIARY") if include_qi else None
    prop = create_property_entity(
        hoa_annual_dues=hoa_annual_dues, tax_annual=tax_annual,
    )

    payload = escrow_file_payload(
        property_id=prop["id"],
        buyer_party_id=buyer["id"],
        seller_party_id=seller["id"],
        lender_party_id=lender["id"] if lender else None,
        qi_party_id=qi["id"] if qi else None,
        purchase_price=purchase_price,
        loan_amount=loan_amount,
        closing_date_planned=closing_date_planned,
        is_1031_exchange=is_1031_exchange,
    )
    resp = api_client.create_escrow_file(
        payload, with_idempotency(eo_headers),
    )
    escrow_file = get_success_data(resp)

    return {
        "property": prop,
        "buyer": buyer,
        "seller": seller,
        "lender": lender,
        "qi": qi,
        "escrow_file": escrow_file,
    }


# ===========================================================================
# Tier 3 — EMD funded (HELD)
# ===========================================================================
def create_emd_held(
    escrow_file_id: str,
    *,
    amount: float = TEST_DEFAULTS["EMD_AMOUNT"],
) -> Dict[str, Any]:
    """Create EMD and fund it to HELD. PRD §3.2: PENDING_FUNDS → HELD
    via POST /earnest-money/{id}/fund."""
    eo_headers = TEST_USERS["escrow_officer_headers"]

    resp = api_client.create_emd(
        emd_payload(escrow_file_id=escrow_file_id, amount=amount),
        with_idempotency(eo_headers),
    )
    emd = get_success_data(resp)

    resp = api_client.fund_emd(
        emd["id"],
        version_only_payload(version=emd["version"]),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def setup_emd_held(
    *,
    purchase_price: float = TEST_DEFAULTS["PURCHASE_PRICE"],
    emd_amount: float = TEST_DEFAULTS["EMD_AMOUNT"],
    loan_amount: float = TEST_DEFAULTS["LOAN_AMOUNT"],
    hoa_annual_dues: float = TEST_DEFAULTS["HOA_ANNUAL_DUES"],
    tax_annual: float = TEST_DEFAULTS["TAX_ANNUAL"],
    closing_date_planned: str = TEST_DEFAULTS["CLOSING_DATE_PLANNED"],
    is_1031_exchange: bool = False,
    include_qi: bool = False,
) -> Dict[str, Any]:
    """Create file + EMD HELD. Returns bundle: property, buyer, seller,
    lender, qi, escrow_file, emd."""
    bundle = create_escrow_file_basic(
        purchase_price=purchase_price,
        loan_amount=loan_amount,
        hoa_annual_dues=hoa_annual_dues,
        tax_annual=tax_annual,
        closing_date_planned=closing_date_planned,
        is_1031_exchange=is_1031_exchange,
        include_qi=include_qi,
    )
    emd = create_emd_held(
        bundle["escrow_file"]["id"], amount=emd_amount,
    )
    bundle["emd"] = emd
    return bundle


# ===========================================================================
# Tier 3 — Title search through CLEARED
# ===========================================================================
def order_title_search(escrow_file_id: str) -> Dict[str, Any]:
    """POST /title-searches. PRD §3.3 — EscrowOfficer or TitleOfficer."""
    to_headers = TEST_USERS["title_officer_headers"]
    resp = api_client.create_title_search(
        title_search_payload(escrow_file_id=escrow_file_id),
        with_idempotency(to_headers),
    )
    return get_success_data(resp)


def submit_title_findings(
    title_search_id: str,
    *,
    chain_of_title_clean: bool = True,
    open_liens_total: float = 0.0,
    encumbrance_count: int = 0,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PATCH /title-searches/{id}. PRD §3.3 — ORDERED → COMPLETED."""
    to_headers = TEST_USERS["title_officer_headers"]
    payload = title_search_findings_payload(
        chain_of_title_clean=chain_of_title_clean,
        open_liens_total=open_liens_total,
        encumbrance_count=encumbrance_count,
        version=version,
    )
    resp = api_client.patch_title_search(
        title_search_id, payload, with_idempotency(to_headers),
    )
    return get_success_data(resp)


def clear_title_search(title_search_id: str,
                       version: Optional[int] = None) -> Dict[str, Any]:
    """POST /title-searches/{id}/clear. PRD §3.3 — COMPLETED → CLEARED."""
    to_headers = TEST_USERS["title_officer_headers"]
    resp = api_client.clear_title_search(
        title_search_id, version_only_payload(version=version),
        with_idempotency(to_headers),
    )
    return get_success_data(resp)


def setup_title_cleared(escrow_file_id: str) -> Dict[str, Any]:
    """Order → submit findings (clean) → clear. Returns the CLEARED
    title search."""
    ts = order_title_search(escrow_file_id)
    ts = submit_title_findings(
        ts["id"], chain_of_title_clean=True, open_liens_total=0.0,
        encumbrance_count=0, version=ts["version"],
    )
    ts = clear_title_search(ts["id"], version=ts["version"])
    return ts


# ===========================================================================
# Tier 3 — Title policy through BOUND
# ===========================================================================
def quote_title_policy(
    escrow_file_id: str,
    *,
    policy_kind: str = "OWNERS",
    insured_amount: float = TEST_DEFAULTS["INSURED_AMOUNT_OWNERS"],
    simultaneous_issue: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /title-policies. PRD §3.3 — TitleOfficer."""
    to_headers = TEST_USERS["title_officer_headers"]
    payload = title_policy_payload(
        escrow_file_id=escrow_file_id,
        policy_kind=policy_kind,
        insured_amount=insured_amount,
        simultaneous_issue=simultaneous_issue,
    )
    resp = api_client.create_title_policy(
        payload, with_idempotency(to_headers),
    )
    return get_success_data(resp)


def bind_title_policy(policy_id: str,
                      version: Optional[int] = None) -> Dict[str, Any]:
    to_headers = TEST_USERS["title_officer_headers"]
    resp = api_client.bind_title_policy(
        policy_id, version_only_payload(version=version),
        with_idempotency(to_headers),
    )
    return get_success_data(resp)


def setup_owners_policy_bound(
    escrow_file_id: str,
    *,
    insured_amount: float = TEST_DEFAULTS["INSURED_AMOUNT_OWNERS"],
) -> Dict[str, Any]:
    """Quote + bind an OWNERS policy. Assumes title is already CLEARED.
    Returns the BOUND policy."""
    policy = quote_title_policy(
        escrow_file_id,
        policy_kind="OWNERS",
        insured_amount=insured_amount,
    )
    return bind_title_policy(policy["id"], version=policy["version"])


# ===========================================================================
# Tier 3 — CCR disclosure (Buyer acts on file)
# ===========================================================================
def create_ccr_disclosure(
    escrow_file_id: str,
    buyer_party_id: str,
    *,
    material_restrictions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """POST /ccr-disclosures. PRD §3.4: Buyer role; X-User-ID must be
    the Party.id of the buyer on that escrow file."""
    headers = with_idempotency(make_buyer_headers(buyer_party_id))
    payload = ccr_disclosure_payload(
        escrow_file_id=escrow_file_id,
        material_restrictions=material_restrictions,
    )
    resp = api_client.create_ccr_disclosure(payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 3 — Escrow file advance
# ===========================================================================
def advance_escrow(escrow_file_id: str) -> Dict[str, Any]:
    """POST /escrow-files/{id}/advance. PRD §3.9 — chain through
    contingent states if preconditions hold."""
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.advance_escrow_file(
        escrow_file_id, with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def re_get_escrow_file(escrow_file_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.get_escrow_file(escrow_file_id, eo_headers)
    return get_success_data(resp)


def re_get_emd(emd_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.get_emd(emd_id, eo_headers)
    return get_success_data(resp)


def re_get_closing_disclosure(cd_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.get_closing_disclosure(cd_id, eo_headers)
    return get_success_data(resp)


def re_get_wire(wire_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.get_wire_instruction(wire_id, eo_headers)
    return get_success_data(resp)


def re_get_disbursement(disb_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.get_disbursement(disb_id, eo_headers)
    return get_success_data(resp)


def re_get_exchange(exchange_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.get_exchange(exchange_id, eo_headers)
    return get_success_data(resp)


def re_get_title_policy(policy_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["title_officer_headers"]
    resp = api_client.get_title_policy(policy_id, eo_headers)
    return get_success_data(resp)


def re_get_title_search(title_search_id: str) -> Dict[str, Any]:
    eo_headers = TEST_USERS["title_officer_headers"]
    resp = api_client.get_title_search(title_search_id, eo_headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 4 — File in CONTINGENT_CD
# ===========================================================================
def setup_escrow_in_contingent_cd(
    *,
    purchase_price: float = TEST_DEFAULTS["PURCHASE_PRICE"],
    loan_amount: float = TEST_DEFAULTS["LOAN_AMOUNT"],
    emd_amount: float = TEST_DEFAULTS["EMD_AMOUNT"],
    hoa_annual_dues: float = TEST_DEFAULTS["HOA_ANNUAL_DUES"],
    tax_annual: float = TEST_DEFAULTS["TAX_ANNUAL"],
    closing_date_planned: str = TEST_DEFAULTS["CLOSING_DATE_PLANNED"],
    is_1031_exchange: bool = False,
    include_qi: bool = False,
) -> Dict[str, Any]:
    """Build a file to CONTINGENT_CD:
       1) parties + property + file (OPEN)
       2) EMD HELD                 → advance to CONTINGENT_TITLE
       3) Title CLEARED, OWNERS BOUND, CCR acknowledged
       4) advance → CONTINGENT_CD

    Returns bundle: property, buyer, seller, lender, qi, escrow_file,
    emd, title_search, owners_policy, ccr.
    """
    bundle = setup_emd_held(
        purchase_price=purchase_price,
        loan_amount=loan_amount,
        emd_amount=emd_amount,
        hoa_annual_dues=hoa_annual_dues,
        tax_annual=tax_annual,
        closing_date_planned=closing_date_planned,
        is_1031_exchange=is_1031_exchange,
        include_qi=include_qi,
    )
    ef_id = bundle["escrow_file"]["id"]

    # OPEN → CONTINGENT_TITLE (EMD HELD precondition).
    bundle["escrow_file"] = advance_escrow(ef_id)

    # Title pipeline → CLEARED.
    title_search = setup_title_cleared(ef_id)
    owners_policy = setup_owners_policy_bound(ef_id)
    ccr = create_ccr_disclosure(ef_id, bundle["buyer"]["id"])

    bundle["title_search"] = title_search
    bundle["owners_policy"] = owners_policy
    bundle["ccr"] = ccr

    # CONTINGENT_TITLE → CONTINGENT_CD.
    bundle["escrow_file"] = advance_escrow(ef_id)
    return bundle


# ===========================================================================
# Tier 4 — Closing disclosure helpers
# ===========================================================================
def create_cd(
    escrow_file_id: str,
    *,
    total_loan_costs: float = TEST_DEFAULTS["TOTAL_LOAN_COSTS"],
    seller_credits: float = TEST_DEFAULTS["SELLER_CREDITS"],
    seller_days_owned: int = TEST_DEFAULTS["SELLER_DAYS_OWNED"],
    issuer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /closing-disclosures. EscrowOfficer creates the DRAFT.
    PRD §3.5: cash_to_close and prorations are frozen at creation."""
    headers = issuer_headers or TEST_USERS["escrow_officer_headers"]
    resp = api_client.create_closing_disclosure(
        closing_disclosure_payload(
            escrow_file_id=escrow_file_id,
            total_loan_costs=total_loan_costs,
            seller_credits=seller_credits,
            seller_days_owned=seller_days_owned,
        ),
        with_idempotency(headers),
    )
    return get_success_data(resp)


def issue_cd(cd_id: str, *, version: Optional[int] = None,
             issuer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /closing-disclosures/{id}/issue.
    The issuer's X-User-ID is the pinned 'latest CD issuer' for the SoD
    check on wire confirm / disbursement approve (PRD §2.11)."""
    headers = issuer_headers or TEST_USERS["escrow_officer_headers"]
    resp = api_client.issue_closing_disclosure(
        cd_id, version_only_payload(version=version),
        with_idempotency(headers),
    )
    return get_success_data(resp)


def acknowledge_cd(cd_id: str, buyer_party_id: str,
                   *, version: Optional[int] = None) -> Dict[str, Any]:
    """POST /closing-disclosures/{id}/acknowledge. PRD §3.5: Buyer
    role; X-User-ID must equal buyer_party_id of the parent file."""
    headers = with_idempotency(make_buyer_headers(buyer_party_id))
    resp = api_client.acknowledge_closing_disclosure(
        cd_id, version_only_payload(version=version), headers,
    )
    return get_success_data(resp)


def promote_cd(cd_id: str, *, version: Optional[int] = None,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /closing-disclosures/{id}/promote. EscrowOfficer."""
    headers = headers or TEST_USERS["escrow_officer_headers"]
    resp = api_client.promote_closing_disclosure(
        cd_id, version_only_payload(version=version),
        with_idempotency(headers),
    )
    return get_success_data(resp)


def setup_escrow_in_contingent_wire(
    *,
    cd_issuer_headers: Optional[Dict[str, str]] = None,
    cd_overrides: Optional[Dict[str, Any]] = None,
    waiting_days: int = 10,
    **escrow_overrides: Any,
) -> Dict[str, Any]:
    """Build a file to CONTINGENT_WIRE. Steps:
      1) Setup to CONTINGENT_CD.
      2) Create CD (DRAFT) under cd_issuer_headers — this is the pinned
         CD issuer for SoD purposes (PRD §2.11).
      3) Issue CD (DRAFT → ISSUED).
      4) Buyer acknowledges (ISSUED → ACKNOWLEDGED).
      5) Advance clock past earliest_funding_at (default +10 days
         comfortably clears any 3-BD window).
      6) Promote (ACKNOWLEDGED → READY_TO_FUND).
      7) Advance escrow (CONTINGENT_CD → CONTINGENT_WIRE).

    Returns bundle with all entities + cd, cd_issuer_id pinned.
    """
    bundle = setup_escrow_in_contingent_cd(**escrow_overrides)
    ef_id = bundle["escrow_file"]["id"]

    cd_overrides = cd_overrides or {}
    issuer_headers = cd_issuer_headers or TEST_USERS["escrow_officer_headers"]
    issuer_id = issuer_headers.get("X-User-ID", ESCROW_OFFICER_ID)

    cd = create_cd(
        ef_id, issuer_headers=issuer_headers, **cd_overrides,
    )
    cd = issue_cd(
        cd["id"], version=cd["version"], issuer_headers=issuer_headers,
    )
    cd = acknowledge_cd(
        cd["id"], bundle["buyer"]["id"], version=cd["version"],
    )

    # Advance clock to clear the 3-business-day cooling-off window.
    advance_clock_by(days=waiting_days)

    cd = promote_cd(cd["id"], version=cd["version"])

    # CONTINGENT_CD → CONTINGENT_WIRE.
    bundle["escrow_file"] = advance_escrow(ef_id)
    bundle["cd"] = cd
    bundle["cd_issuer_id"] = issuer_id
    bundle["cd_issuer_headers"] = issuer_headers
    return bundle


# ===========================================================================
# Tier 4 — Wires + Disbursements
# ===========================================================================
def create_wire(
    escrow_file_id: str,
    beneficiary_kind: str,
    beneficiary_party_id: str,
    *,
    routing_number: str = TEST_DEFAULTS["ROUTING_NUMBER"],
    account_number_last4: str = TEST_DEFAULTS["ACCOUNT_LAST4"],
) -> Dict[str, Any]:
    """POST /wire-instructions."""
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.create_wire_instruction(
        wire_instruction_payload(
            escrow_file_id=escrow_file_id,
            beneficiary_kind=beneficiary_kind,
            beneficiary_party_id=beneficiary_party_id,
            routing_number=routing_number,
            account_number_last4=account_number_last4,
        ),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def submit_wire(wire_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.submit_wire_instruction(
        wire_id, version_only_payload(version=version),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def confirm_wire(
    wire_id: str,
    *,
    confirmer_headers: Optional[Dict[str, str]] = None,
    callback_channel: str = "VOICE_VERIFIED",
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /wire-instructions/{id}/confirm-callback. PRD §2.11/§3.6:
    confirmer's X-User-ID MUST differ from the CD issuer."""
    headers = confirmer_headers or TEST_USERS["disb_approver_headers"]
    resp = api_client.confirm_callback_wire(
        wire_id,
        confirm_callback_payload(
            callback_completed=True,
            callback_channel=callback_channel,
            version=version,
        ),
        with_idempotency(headers),
    )
    return get_success_data(resp)


def setup_confirmed_wire(
    escrow_file_id: str,
    beneficiary_kind: str,
    beneficiary_party_id: str,
    *,
    confirmer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create wire → submit → confirm-callback. Confirmer defaults to a
    DisbursementApprover (always SoD-clean against the canonical CD
    issuer)."""
    wire = create_wire(
        escrow_file_id, beneficiary_kind, beneficiary_party_id,
    )
    wire = submit_wire(wire["id"], version=wire["version"])
    wire = confirm_wire(
        wire["id"], confirmer_headers=confirmer_headers,
        version=wire["version"],
    )
    return wire


def create_disbursement(
    escrow_file_id: str,
    wire_instruction_id: str,
    amount: float,
) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.create_disbursement(
        disbursement_payload(
            escrow_file_id=escrow_file_id,
            wire_instruction_id=wire_instruction_id,
            amount=amount,
        ),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def approve_disbursement(
    disb_id: str,
    *,
    approver_headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /disbursements/{id}/approve. PRD §3.7: DisbursementApprover;
    X-User-ID must differ from CD issuer."""
    headers = approver_headers or TEST_USERS["disb_approver_headers"]
    resp = api_client.approve_disbursement(
        disb_id, version_only_payload(version=version),
        with_idempotency(headers),
    )
    return get_success_data(resp)


def send_disbursement(
    disb_id: str,
    *,
    approver_headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    headers = approver_headers or TEST_USERS["disb_approver_headers"]
    resp = api_client.send_disbursement(
        disb_id, version_only_payload(version=version),
        with_idempotency(headers),
    )
    return get_success_data(resp)


def settle_disbursement(
    disb_id: str,
    *,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.7: EscrowOfficer settles."""
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.settle_disbursement(
        disb_id, version_only_payload(version=version),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def setup_disbursement_settled(
    escrow_file_id: str,
    wire_instruction_id: str,
    amount: float,
    *,
    approver_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create → approve → send → settle."""
    disb = create_disbursement(escrow_file_id, wire_instruction_id, amount)
    disb = approve_disbursement(
        disb["id"], approver_headers=approver_headers,
        version=disb["version"],
    )
    disb = send_disbursement(
        disb["id"], approver_headers=approver_headers,
        version=disb["version"],
    )
    disb = settle_disbursement(disb["id"], version=disb["version"])
    return disb


# ===========================================================================
# Tier 5 — Ready to close
# ===========================================================================
def setup_escrow_ready_to_close(
    *,
    seller_wire_amount: Optional[float] = None,
    cd_issuer_headers: Optional[Dict[str, str]] = None,
    waiting_days: int = 10,
    **escrow_overrides: Any,
) -> Dict[str, Any]:
    """Build a file to READY_TO_CLOSE:
      1) CONTINGENT_WIRE.
      2) Create + submit + confirm wire to SELLER (via SoD-clean
         confirmer).
      3) Advance escrow (CONTINGENT_WIRE → READY_TO_CLOSE).

    Returns bundle with seller_wire pinned.
    """
    bundle = setup_escrow_in_contingent_wire(
        cd_issuer_headers=cd_issuer_headers,
        waiting_days=waiting_days,
        **escrow_overrides,
    )
    ef = bundle["escrow_file"]
    seller_party_id = bundle["seller"]["id"]
    seller_wire = setup_confirmed_wire(
        ef["id"], "SELLER", seller_party_id,
    )
    bundle["seller_wire"] = seller_wire

    bundle["escrow_file"] = advance_escrow(ef["id"])
    return bundle


# ===========================================================================
# Tier 4 — Exchange1031 helpers
# ===========================================================================
def create_exchange_initiated(
    escrow_file_id: str,
    *,
    relinquished_basis: float = 200000.00,
    relinquished_sale_price: float = 500000.00,
    cash_boot_received: float = 50000.00,
    mortgage_relief: float = 20000.00,
) -> Dict[str, Any]:
    """POST /exchanges. PRD §3.8 — INITIATED."""
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.create_exchange(
        exchange_payload(
            escrow_file_id=escrow_file_id,
            relinquished_basis=relinquished_basis,
            relinquished_sale_price=relinquished_sale_price,
            cash_boot_received=cash_boot_received,
            mortgage_relief=mortgage_relief,
        ),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def identify_exchange(exchange_id: str,
                      version: Optional[int] = None) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.identify_exchange(
        exchange_id, version_only_payload(version=version),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def fail_exchange(exchange_id: str,
                  version: Optional[int] = None) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.fail_exchange(
        exchange_id, version_only_payload(version=version),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4 — Release EMD helpers
# ===========================================================================
def release_emd_with_reason(
    emd_id: str,
    reason: str,
    *,
    version: Optional[int] = None,
    split_buyer_share: Optional[float] = None,
    split_seller_share: Optional[float] = None,
) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    payload = emd_release_payload(
        reason=reason,
        split_buyer_share=split_buyer_share,
        split_seller_share=split_seller_share,
        version=version,
    )
    resp = api_client.release_emd(
        emd_id, payload, with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def cancel_escrow(
    escrow_file_id: str,
    cancel_reason: str,
    *,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    payload = cancel_escrow_payload(
        cancel_reason=cancel_reason, version=version,
    )
    resp = api_client.cancel_escrow_file(
        escrow_file_id, payload, with_idempotency(eo_headers),
    )
    return get_success_data(resp)


def revise_cd(
    cd_id: str,
    *,
    triggering_change_kind: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    eo_headers = TEST_USERS["escrow_officer_headers"]
    resp = api_client.revise_closing_disclosure(
        cd_id,
        revise_cd_payload(
            triggering_change_kind=triggering_change_kind,
            version=version,
        ),
        with_idempotency(eo_headers),
    )
    return get_success_data(resp)


# ===========================================================================
# Convenience: distinct identity headers
# ===========================================================================
def distinct_cd_issuer_and_confirmer() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (cd_issuer_headers, sod_clean_confirmer_headers) — two
    different opaque actor ids. The first is canonical EscrowOfficer A
    (CD issuer); the second is a DisbursementApprover whose id ≠ A.
    """
    return (
        TEST_USERS["escrow_officer_headers"],
        TEST_USERS["disb_approver_headers"],
    )


def same_cd_issuer_for_sod_violation() -> Dict[str, str]:
    """Return headers identifying the SAME actor as the canonical CD
    issuer. Used for SoD-violation tests where the CD issuer attempts
    to confirm a wire or approve a disbursement (PRD §2.11)."""
    return TEST_USERS["escrow_officer_headers"]


__all__ = [
    # Clock
    "get_clock_now",
    "server_now_dt",
    "advance_clock_to",
    "advance_clock_by",
    # Tier 1
    "create_party",
    "create_property_entity",
    # Tier 2
    "create_escrow_file_basic",
    # Tier 3
    "create_emd_held",
    "setup_emd_held",
    "order_title_search",
    "submit_title_findings",
    "clear_title_search",
    "setup_title_cleared",
    "quote_title_policy",
    "bind_title_policy",
    "setup_owners_policy_bound",
    "create_ccr_disclosure",
    "advance_escrow",
    "re_get_escrow_file",
    "re_get_emd",
    "re_get_closing_disclosure",
    "re_get_wire",
    "re_get_disbursement",
    "re_get_exchange",
    "re_get_title_policy",
    "re_get_title_search",
    # Tier 4
    "setup_escrow_in_contingent_cd",
    "create_cd",
    "issue_cd",
    "acknowledge_cd",
    "promote_cd",
    "setup_escrow_in_contingent_wire",
    "create_wire",
    "submit_wire",
    "confirm_wire",
    "setup_confirmed_wire",
    "create_disbursement",
    "approve_disbursement",
    "send_disbursement",
    "settle_disbursement",
    "setup_disbursement_settled",
    "create_exchange_initiated",
    "identify_exchange",
    "fail_exchange",
    "release_emd_with_reason",
    "cancel_escrow",
    "revise_cd",
    # Tier 5
    "setup_escrow_ready_to_close",
    # Identity helpers
    "distinct_cd_issuer_and_confirmer",
    "same_cd_issuer_for_sod_violation",
]
