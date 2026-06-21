"""Composite setup helpers for the Title Insurance Escrow API.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Setup calls use the
lenient get_success_data() validator so a broken preamble surfaces as a clear
"Setup failed" rather than a confusing assertion error downstream.

Identity threading: the Agency role is entity-backed (PRD §2.1) — ownership-gated
calls (open/cancel order, deposit) MUST use make_agency_headers(agency["id"]).
TitleOfficer and Underwriter are opaque and use shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_agency_headers
from .factories import (
    create_agency_payload,
    create_order_payload,
    create_title_search_payload,
    create_commitment_payload,
    create_exception_payload,
    create_policy_payload,
    create_endorsement_payload,
    create_deposit_payload,
    create_disbursement_payload,
    create_claim_payload,
    create_curative_action_payload,
)

TO = TEST_USERS["title_officer_headers"]      # TitleOfficer (opaque)
UW = TEST_USERS["underwriter_headers"]         # Underwriter (opaque)


# ---------------------------------------------------------------------------
# Tier 1: primitives
# ---------------------------------------------------------------------------
def create_agency(remit_split_pct=0.82, name="Acme Title"):
    """Register an ACTIVE agency. Returns the agency dict."""
    resp = api_client.create_agency(
        create_agency_payload(name=name, remit_split_pct=remit_split_pct), UW
    )
    return get_success_data(resp)


def create_order(agency, **order_overrides):
    """Open an OPENED order owned by `agency`. Returns the order dict."""
    headers = make_agency_headers(agency["id"])
    resp = api_client.create_order(
        create_order_payload(agency["id"], **order_overrides), headers
    )
    return get_success_data(resp)


def create_agency_and_order(remit_split_pct=0.82, **order_overrides):
    """Agency + one OPENED order. Returns (agency, order)."""
    agency = create_agency(remit_split_pct=remit_split_pct)
    order = create_order(agency, **order_overrides)
    return agency, order


def get_order(order_id):
    """Re-fetch an order (e.g. to read its current version). Returns the order dict."""
    return get_success_data(api_client.get_order(order_id, UW))


# ---------------------------------------------------------------------------
# Tier 1/2: commitments
# ---------------------------------------------------------------------------
def create_draft_commitment(order, insured_amount_cents=25_000_000, **overrides):
    """Create a DRAFT commitment under `order` using the order's current version.
    Returns the commitment dict."""
    fresh = get_order(order["id"])
    payload = create_commitment_payload(
        fresh["version"], insured_amount_cents=insured_amount_cents, **overrides
    )
    resp = api_client.create_commitment(order["id"], payload, TO)
    return get_success_data(resp)


def create_issued_commitment(order, insured_amount_cents=25_000_000, **overrides):
    """Create a DRAFT commitment and transition it to ISSUED. Returns the commitment dict."""
    commitment = create_draft_commitment(order, insured_amount_cents=insured_amount_cents, **overrides)
    resp = api_client.transition_commitment(commitment["id"], {"to_status": "ISSUED"}, TO)
    return get_success_data(resp)


def setup_order_with_issued_commitment(insured_amount_cents=25_000_000,
                                       remit_split_pct=0.82, **order_overrides):
    """Agency + OPENED order + one ISSUED commitment. Returns (agency, order, commitment)."""
    agency, order = create_agency_and_order(remit_split_pct=remit_split_pct, **order_overrides)
    commitment = create_issued_commitment(order, insured_amount_cents=insured_amount_cents)
    return agency, order, commitment


# ---------------------------------------------------------------------------
# Tier 1/2: exceptions
# ---------------------------------------------------------------------------
def add_exception(commitment, **overrides):
    """Raise a Schedule B exception on `commitment`. Returns the exception dict."""
    resp = api_client.create_exception(
        commitment["id"], create_exception_payload(**overrides), TO
    )
    return get_success_data(resp)


def add_exception_in_curative_pending(commitment, **overrides):
    """Raise an exception and move it to CURATIVE_PENDING. Returns the exception dict."""
    overrides.setdefault("curative_required", True)
    ex = add_exception(commitment, **overrides)
    resp = api_client.transition_exception(ex["id"], {"to_status": "CURATIVE_PENDING"}, TO)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: policies + remittances
# ---------------------------------------------------------------------------
def create_pending_policy(order, commitment, coverage_amount_cents=25_000_000, **overrides):
    """Create a PENDING policy bound to `commitment`. Returns the policy dict."""
    resp = api_client.create_policy(
        order["id"],
        create_policy_payload(commitment["id"], coverage_amount_cents=coverage_amount_cents, **overrides),
        UW,
    )
    return get_success_data(resp)


def issue_policy(policy):
    """Transition a PENDING policy to ISSUED (computes premium, creates remittance).
    Returns the issued policy dict."""
    resp = api_client.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW)
    return get_success_data(resp)


def get_policy_remittance(policy):
    """Return the (single) PremiumRemittance dict created when the policy was issued."""
    resp = api_client.list_remittances(policy["id"], UW)
    data, _meta = _paginated(resp)
    assert data, "expected a PremiumRemittance after policy issue"
    return data[0]


def setup_issued_owner_policy(coverage_amount_cents=25_000_000, insured_amount_cents=25_000_000,
                              remit_split_pct=0.82, is_reissue=False, **order_overrides):
    """Agency + order + ISSUED commitment + ISSUED OWNER policy (+ its PENDING remittance).
    Returns (agency, order, commitment, policy)."""
    agency, order, commitment = setup_order_with_issued_commitment(
        insured_amount_cents=insured_amount_cents, remit_split_pct=remit_split_pct, **order_overrides
    )
    policy = create_pending_policy(
        order, commitment, coverage_amount_cents=coverage_amount_cents, is_reissue=is_reissue
    )
    policy = issue_policy(policy)
    return agency, order, commitment, policy


# ---------------------------------------------------------------------------
# Tier 1/3: title searches + order progression
# ---------------------------------------------------------------------------
def add_title_search(order, searched_parcel_id=None, **overrides):
    """Order a TitleSearch (ORDERED) under `order`. Returns the search dict."""
    if searched_parcel_id is None:
        searched_parcel_id = order["parcel_id"]
    resp = api_client.create_title_search(
        order["id"], create_title_search_payload(searched_parcel_id=searched_parcel_id, **overrides), TO
    )
    return get_success_data(resp)


def complete_title_search(search, chain_verified=True,
                          gap_from_date="2026-01-05T00:00:00Z",
                          gap_to_date="2026-01-20T00:00:00Z"):
    """Walk ORDERED -> IN_EXAM -> COMPLETED persisting the gap window. Returns the search dict."""
    get_success_data(api_client.transition_title_search(search["id"], {"to_status": "IN_EXAM"}, TO))
    resp = api_client.transition_title_search(
        search["id"],
        {
            "to_status": "COMPLETED",
            "chain_verified": chain_verified,
            "gap_from_date": gap_from_date,
            "gap_to_date": gap_to_date,
        },
        TO,
    )
    return get_success_data(resp)


def transition_order(order_id, to_status, agency=None):
    """Transition an order. Agency-driven transitions (CANCEL) use the agency identity;
    TitleOfficer drives production transitions. Returns the order dict."""
    if agency is not None:
        headers = make_agency_headers(agency["id"])
    else:
        headers = TO
    resp = api_client.transition_order(order_id, {"to_status": to_status}, headers)
    return get_success_data(resp)


def setup_order_clear_to_close(coverage_amount_cents=25_000_000, insured_amount_cents=25_000_000,
                               remit_split_pct=0.82, gap_to_date="2026-01-20T00:00:00Z",
                               **order_overrides):
    """Drive a full pipeline OPENED -> IN_TITLE -> COMMITTED -> CLEAR_TO_CLOSE:
    agency + order + ISSUED commitment + COMPLETED chain-verified search + ISSUED OWNER policy,
    then CLEAR_TO_CLOSE. Returns (agency, order, commitment, search, policy).
    The order dict returned reflects the CLEAR_TO_CLOSE state.
    """
    agency, order, commitment = setup_order_with_issued_commitment(
        insured_amount_cents=insured_amount_cents, remit_split_pct=remit_split_pct, **order_overrides
    )
    search = add_title_search(order)
    transition_order(order["id"], "IN_TITLE")
    search = complete_title_search(search, gap_to_date=gap_to_date)
    transition_order(order["id"], "COMMITTED")
    policy = create_pending_policy(order, commitment, coverage_amount_cents=coverage_amount_cents)
    policy = issue_policy(policy)
    order = transition_order(order["id"], "CLEAR_TO_CLOSE")
    return agency, order, commitment, search, policy


# ---------------------------------------------------------------------------
# Tier 4: escrow / deposits / disbursements
# ---------------------------------------------------------------------------
def add_deposit(order, agency, amount_cents=100_000, source_ref="WIRE-IN-1"):
    """Record a RECEIVED deposit (agency-owned). Returns the deposit dict."""
    headers = make_agency_headers(agency["id"])
    resp = api_client.create_deposit(
        order["id"], create_deposit_payload(amount_cents=amount_cents, source_ref=source_ref), headers
    )
    return get_success_data(resp)


def add_posted_deposit(order, agency, amount_cents=100_000, source_ref="WIRE-IN-1"):
    """Record a deposit and POST it (counts toward balance). Returns the deposit dict."""
    deposit = add_deposit(order, agency, amount_cents=amount_cents, source_ref=source_ref)
    resp = api_client.transition_deposit(deposit["id"], {"to_status": "POSTED"}, UW)
    return get_success_data(resp)


def add_disbursement(order, amount_cents=100_000, purpose="SELLER_PROCEEDS", payee="Seller",
                     wire_window_start="2026-01-20T09:00:00Z",
                     wire_window_end="2026-01-20T10:00:00Z"):
    """Create a REQUESTED disbursement, reading the order's current version for OCC.
    Returns the disbursement dict."""
    fresh = get_order(order["id"])
    payload = create_disbursement_payload(
        fresh["version"],
        amount_cents=amount_cents,
        purpose=purpose,
        payee=payee,
        wire_window_start=wire_window_start,
        wire_window_end=wire_window_end,
    )
    resp = api_client.create_disbursement(order["id"], payload, UW)
    return get_success_data(resp)


def add_approved_disbursement(order, amount_cents=100_000, purpose="SELLER_PROCEEDS", payee="Seller",
                              wire_window_start="2026-01-20T09:00:00Z",
                              wire_window_end="2026-01-20T10:00:00Z"):
    """Create a disbursement and APPROVE it. Returns the disbursement dict."""
    disb = add_disbursement(
        order, amount_cents=amount_cents, purpose=purpose, payee=payee,
        wire_window_start=wire_window_start, wire_window_end=wire_window_end,
    )
    resp = api_client.transition_disbursement(disb["id"], {"to_status": "APPROVED"}, UW)
    return get_success_data(resp)


def add_wired_disbursement(order, amount_cents=100_000, purpose="SELLER_PROCEEDS", payee="Seller",
                           wire_window_start="2026-01-20T09:00:00Z",
                           wire_window_end="2026-01-20T10:00:00Z"):
    """Create -> APPROVE -> WIRE a disbursement. Returns the disbursement dict."""
    disb = add_approved_disbursement(
        order, amount_cents=amount_cents, purpose=purpose, payee=payee,
        wire_window_start=wire_window_start, wire_window_end=wire_window_end,
    )
    resp = api_client.transition_disbursement(disb["id"], {"to_status": "WIRED"}, UW)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3/5: claims + curative
# ---------------------------------------------------------------------------
def file_claim(policy, claim_type="UNDISCLOSED_LIEN", estimated_loss_cents=50_000):
    """File a claim (FNOL) under an ISSUED policy. Returns the claim dict."""
    resp = api_client.create_claim(
        policy["id"], create_claim_payload(claim_type=claim_type, estimated_loss_cents=estimated_loss_cents), UW
    )
    return get_success_data(resp)


def advance_claim_to_investigating(claim):
    """Transition FNOL -> INVESTIGATING (computes the provisional reserve). Returns the claim dict."""
    resp = api_client.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW)
    return get_success_data(resp)


def advance_claim_to_curative(claim):
    """Transition a claim to CURATIVE (via INVESTIGATING). Returns the claim dict at CURATIVE."""
    advance_claim_to_investigating(claim)
    resp = api_client.transition_claim(claim["id"], {"to_status": "CURATIVE"}, UW)
    return get_success_data(resp)


def add_curative_action(order, subject_type, subject_id, action_type="PAYOFF", resolve=False):
    """Open a CurativeAction on the order against an exception or claim; optionally RESOLVE it.
    Returns the curative action dict."""
    resp = api_client.create_curative_action(
        order["id"], create_curative_action_payload(subject_type, subject_id, action_type=action_type), TO
    )
    action = get_success_data(resp)
    if resolve:
        resolved = api_client.transition_curative_action(action["id"], {"to_status": "RESOLVED"}, UW)
        action = get_success_data(resolved)
    return action


# ---------------------------------------------------------------------------
# internal
# ---------------------------------------------------------------------------
def _paginated(resp):
    """Lenient extraction of (data_list, meta) from a list response for setup use."""
    body = resp.json()
    return body.get("data", []), body.get("meta", {})
