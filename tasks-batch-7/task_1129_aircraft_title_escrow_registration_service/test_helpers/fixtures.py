"""
Composite setup helpers for multi-step test prerequisites.

Most claims about this platform require the system to be in a state that takes
5-15 API calls to reach (file -> search -> liens -> releases -> funding ->
close -> filings). These helpers encapsulate those sequences so tests focus on
assertions. All helpers use get_success_data() so a broken setup surfaces as a
clear "Setup step failed" error naming the endpoint's error_id.

Identity threading: LenderRep is entity-backed by Party, so every identity-gated
lender call (quote / receive-release) goes through make_lender_headers(lender_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_aircraft_payload,
    create_disbursement_payload,
    create_document_payload,
    create_escrow_file_payload,
    create_filing_payload,
    create_finding_payload,
    create_party_payload,
    create_quote_payload,
    create_trust_agreement_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_lender_headers, make_manager_headers

OFFICER = TEST_USERS["officer_headers"]
MANAGER = TEST_USERS["manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
DEFAULT_CLOSE_DATE = "2026-06-30"
DEFAULT_GOOD_THROUGH = "2026-06-30"


# ── Primitive steps ──────────────────────────────────────────────────

def set_clock(to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), MANAGER))


def create_aircraft(n_number="N100TS", serial_number="S-1", make_model="Cessna 172",
                    year=2010, is_international_registry=None):
    overrides = {}
    if is_international_registry is not None:
        overrides["is_international_registry"] = is_international_registry
    payload = create_aircraft_payload(
        n_number=n_number, serial_number=serial_number,
        make_model=make_model, year=year, **overrides,
    )
    return get_success_data(api_client.create_aircraft(payload, OFFICER))


def create_party(party_type, legal_name, **extra):
    return get_success_data(
        api_client.create_party(create_party_payload(party_type, legal_name, **extra), OFFICER)
    )


def create_buyer_seller(buyer_name="Buyer Co", seller_name="Seller Co"):
    return create_party("BUYER", buyer_name), create_party("SELLER", seller_name)


def create_escrow_file(aircraft_id, buyer_id, seller_id, **overrides):
    payload = create_escrow_file_payload(
        aircraft_id=aircraft_id, buyer_party_id=buyer_id,
        seller_party_id=seller_id, **overrides,
    )
    return get_success_data(api_client.create_escrow_file(payload, OFFICER))


def get_aircraft(aircraft_id, headers=None):
    return get_success_data(api_client.get_aircraft(aircraft_id, headers or OFFICER))


def get_escrow_file(file_id, headers=None):
    return get_success_data(api_client.get_escrow_file(file_id, headers or OFFICER))


def get_statement(file_id, headers=None):
    return get_success_data(api_client.get_escrow_file_statement(file_id, headers or OFFICER))


def order_title_search(file_id):
    return get_success_data(api_client.order_title_search(file_id, OFFICER))


def complete_title_search(search_id, findings):
    return get_success_data(
        api_client.complete_title_search(search_id, {"findings": findings}, OFFICER)
    )


def list_liens(params=None):
    return get_success_data(api_client.list_liens(OFFICER, params=params or {}))


def liens_for_file(file_id):
    return list_liens({"escrow_file_id": file_id})


def lien_by_amount(file_id, original_amount_cents):
    """Locate a lien row by its frozen face amount (findings carry it verbatim)."""
    matches = [l for l in liens_for_file(file_id)
               if l["original_amount_cents"] == original_amount_cents]
    assert len(matches) == 1, (
        f"expected exactly one lien of {original_amount_cents} on {file_id}, "
        f"got {len(matches)}"
    )
    return matches[0]


def get_lien(lien_id):
    return get_success_data(api_client.get_lien(lien_id, OFFICER))


def request_lien_release(lien_id):
    return get_success_data(api_client.request_lien_release(lien_id, OFFICER))


def quote_release_flat(release_id, lender_party_id, quoted_payoff_cents,
                       good_through_date=DEFAULT_GOOD_THROUGH):
    payload = create_quote_payload("FLAT", quoted_payoff_cents, good_through_date)
    return get_success_data(
        api_client.quote_release(release_id, payload, make_lender_headers(lender_party_id))
    )


def quote_release_per_diem(release_id, lender_party_id, quoted_payoff_cents,
                           per_diem_cents, good_through_date=DEFAULT_GOOD_THROUGH):
    payload = create_quote_payload(
        "PER_DIEM", quoted_payoff_cents, good_through_date,
        per_diem_cents=per_diem_cents,
    )
    return get_success_data(
        api_client.quote_release(release_id, payload, make_lender_headers(lender_party_id))
    )


def receive_release(release_id, lender_party_id):
    return get_success_data(
        api_client.receive_release(release_id, make_lender_headers(lender_party_id))
    )


def file_release(release_id):
    return get_success_data(api_client.file_release(release_id, OFFICER))


def record_release(release_id):
    return get_success_data(api_client.record_release(release_id, OFFICER))


def create_deposit(file_id, payer_party_id, amount_cents, purpose="BUYER_FUNDS"):
    """OCC-guarded deposit using a freshly read file version."""
    version = get_escrow_file(file_id)["version"]
    payload = {
        "payer_party_id": payer_party_id,
        "amount_cents": amount_cents,
        "purpose": purpose,
        "expected_escrow_file_version": version,
    }
    return get_success_data(api_client.create_deposit(file_id, payload, OFFICER))


def return_deposit(deposit_id):
    return get_success_data(api_client.return_deposit(deposit_id, OFFICER))


def fund_file_to_due(file_id, payer_party_id, purpose="BUYER_FUNDS"):
    """Deposit exactly buyer_amount_due_cents (equality counts -> FUNDED)."""
    due = get_statement(file_id)["buyer_amount_due_cents"]
    create_deposit(file_id, payer_party_id, due, purpose)
    return get_escrow_file(file_id)


def close_escrow_file(file_id):
    """OCC-guarded close using a freshly read file version."""
    version = get_escrow_file(file_id)["version"]
    return get_success_data(
        api_client.close_escrow_file(
            file_id, {"expected_escrow_file_version": version}, OFFICER,
        )
    )


def draft_disbursement(file_id, payee_party_id, amount_cents, purpose,
                       lien_id=None, drafter_headers=None):
    """OCC-guarded draft using a freshly read file version; lands PENDING_APPROVAL."""
    version = get_escrow_file(file_id)["version"]
    payload = create_disbursement_payload(
        payee_party_id, amount_cents, purpose, version,
    )
    if lien_id is not None:
        payload["lien_id"] = lien_id
    return get_success_data(
        api_client.create_disbursement(file_id, payload, drafter_headers or OFFICER)
    )


def approve_disbursement(disbursement_id, manager_user_id="mgr-1"):
    return get_success_data(
        api_client.approve_disbursement(
            disbursement_id, make_manager_headers(manager_user_id),
        )
    )


def release_disbursement(disbursement_id, manager_user_id="mgr-1"):
    return get_success_data(
        api_client.release_disbursement(
            disbursement_id, make_manager_headers(manager_user_id),
        )
    )


def create_filing(file_id, filing_type):
    return get_success_data(
        api_client.create_filing(file_id, create_filing_payload(filing_type), OFFICER)
    )


def get_filing(filing_id, headers=None):
    return get_success_data(api_client.get_filing(filing_id, headers or OFFICER))


def submit_filing(filing_id):
    return get_success_data(api_client.submit_filing(filing_id, OFFICER))


def accept_filing(filing_id, confirmation_code):
    return get_success_data(
        api_client.accept_filing(filing_id, {"confirmation_code": confirmation_code}, OFFICER)
    )


def verify_filing(filing_id, recorded_confirmation_code):
    return get_success_data(
        api_client.verify_filing(
            filing_id, {"recorded_confirmation_code": recorded_confirmation_code}, OFFICER,
        )
    )


def create_document(file_id, doc_type, required_signer_party_ids):
    return get_success_data(
        api_client.create_document(
            file_id,
            create_document_payload(doc_type, required_signer_party_ids),
            OFFICER,
        )
    )


def send_document(document_id):
    return get_success_data(api_client.send_document(document_id, OFFICER))


def sign_document(document_id, signer_party_id):
    return get_success_data(
        api_client.sign_document(document_id, {"signer_party_id": signer_party_id}, OFFICER)
    )


def create_trust_agreement(aircraft_id, trustee_party_id, **overrides):
    return get_success_data(
        api_client.create_trust_agreement(
            create_trust_agreement_payload(aircraft_id, trustee_party_id, **overrides),
            OFFICER,
        )
    )


def submit_trust_agreement(trust_id):
    return get_success_data(api_client.submit_trust_agreement(trust_id, OFFICER))


def accept_trust_agreement(trust_id):
    return get_success_data(api_client.accept_trust_agreement(trust_id, MANAGER))


def make_finding(lienor_party_id, amount_cents, lien_type="FAA_RECORDED",
                 filed_at="2025-01-10", ir_registered_at=None, lienor_name="Lender Co"):
    overrides = {}
    if ir_registered_at is not None:
        overrides["ir_registered_at"] = ir_registered_at
    return create_finding_payload(
        lienor_party_id, amount_cents, lien_type=lien_type,
        lienor_name=lienor_name, filed_at=filed_at, **overrides,
    )


# ── Tier 1/2: state progression + entity hierarchy ──────────────────

def setup_basic_file(clock=DEFAULT_CLOCK, aircraft_overrides=None,
                     file_overrides=None, with_lender=False, with_trustee=False):
    """Aircraft + buyer + seller (+ optional lender/trustee) + OPENED escrow file."""
    if clock is not None:
        set_clock(clock)
    aircraft = create_aircraft(**(aircraft_overrides or {}))
    buyer, seller = create_buyer_seller()
    lender = create_party("LENDER", "Lender Co") if with_lender else None
    trustee = (
        create_party("TRUSTEE", "Trustee Co", is_citizenship_verified=True)
        if with_trustee else None
    )
    overrides = dict(file_overrides or {})
    if lender is not None:
        overrides.setdefault("lender_party_id", lender["id"])
    if trustee is not None:
        overrides.setdefault("trustee_party_id", trustee["id"])
    escrow_file = create_escrow_file(aircraft["id"], buyer["id"], seller["id"], **overrides)
    return {
        "aircraft": aircraft,
        "buyer": buyer,
        "seller": seller,
        "lender": lender,
        "trustee": trustee,
        "file": escrow_file,
    }


def setup_file_with_search(findings=(), **kwargs):
    """OPENED file + title search ordered + completed with the given findings.

    Clean findings -> posture READY, file bubbles to CLEARED; findings with
    liens -> file stays SEARCH_COMPLETE with posture LIEN_BLOCKED.
    """
    ctx = setup_basic_file(**kwargs)
    search = order_title_search(ctx["file"]["id"])
    search = complete_title_search(search["id"], list(findings))
    ctx["search"] = search
    ctx["file"] = get_escrow_file(ctx["file"]["id"])
    return ctx


def setup_cleared_file(**kwargs):
    """File in CLEARED via a clean (zero-finding) completed search."""
    ctx = setup_file_with_search(findings=[], **kwargs)
    assert ctx["file"]["status"] == "CLEARED", (
        f"setup expected CLEARED, got {ctx['file']['status']}"
    )
    return ctx


def setup_funded_file(**kwargs):
    """File in FUNDED: clean search, then a deposit of exactly buyer_amount_due_cents."""
    ctx = setup_cleared_file(**kwargs)
    ctx["file"] = fund_file_to_due(ctx["file"]["id"], ctx["buyer"]["id"])
    assert ctx["file"]["status"] == "FUNDED", (
        f"setup expected FUNDED, got {ctx['file']['status']}"
    )
    return ctx


def setup_closed_file(**kwargs):
    """File in CLOSED: FUNDED then closed with a fresh OCC version."""
    ctx = setup_funded_file(**kwargs)
    ctx["file"] = close_escrow_file(ctx["file"]["id"])
    assert ctx["file"]["status"] == "CLOSED", (
        f"setup expected CLOSED, got {ctx['file']['status']}"
    )
    return ctx


# ── Tier 3: lien release lifecycle shortcuts ────────────────────────

def setup_file_with_lien(amount_cents=500_000, lien_type="FAA_RECORDED",
                         filed_at="2025-03-01", ir_registered_at=None, **kwargs):
    """File with one DISCOVERED lien from a completed search (posture LIEN_BLOCKED)."""
    return _setup_file_with_lien_impl(
        amount_cents, lien_type, filed_at, ir_registered_at, **kwargs,
    )


def _setup_file_with_lien_impl(amount_cents, lien_type, filed_at, ir_registered_at,
                               **kwargs):
    ctx = setup_basic_file(with_lender=True, **kwargs)
    lender = ctx["lender"]
    search = order_title_search(ctx["file"]["id"])
    finding = make_finding(
        lender["id"], amount_cents, lien_type=lien_type, filed_at=filed_at,
        ir_registered_at=ir_registered_at,
    )
    ctx["search"] = complete_title_search(search["id"], [finding])
    ctx["lien"] = lien_by_amount(ctx["file"]["id"], amount_cents)
    ctx["file"] = get_escrow_file(ctx["file"]["id"])
    return ctx


def setup_lien_release_filed(amount_cents=500_000, payoff_basis="FLAT",
                             quoted_payoff_cents=500_000, per_diem_cents=None,
                             good_through_date=DEFAULT_GOOD_THROUGH, **kwargs):
    """File + one lien + a LienRelease walked REQUESTED -> QUOTED -> RELEASE_RECEIVED -> FILED."""
    ctx = _setup_file_with_lien_impl(amount_cents, kwargs.pop("lien_type", "FAA_RECORDED"),
                                     kwargs.pop("filed_at", "2025-03-01"),
                                     kwargs.pop("ir_registered_at", None), **kwargs)
    lender_id = ctx["lender"]["id"]
    release = request_lien_release(ctx["lien"]["id"])
    if payoff_basis == "FLAT":
        release = quote_release_flat(release["id"], lender_id, quoted_payoff_cents,
                                     good_through_date)
    else:
        release = quote_release_per_diem(release["id"], lender_id, quoted_payoff_cents,
                                         per_diem_cents, good_through_date)
    release = receive_release(release["id"], lender_id)
    release = file_release(release["id"])
    ctx["release"] = release
    ctx["file"] = get_escrow_file(ctx["file"]["id"])
    return ctx


def setup_lien_released(amount_cents=500_000, quoted_payoff_cents=500_000, **kwargs):
    """File + one lien whose FLAT release is RECORDED (lien RELEASED, posture READY)."""
    ctx = setup_lien_release_filed(
        amount_cents=amount_cents, payoff_basis="FLAT",
        quoted_payoff_cents=quoted_payoff_cents, **kwargs,
    )
    ctx["release"] = record_release(ctx["release"]["id"])
    ctx["lien"] = get_lien(ctx["lien"]["id"])
    ctx["file"] = get_escrow_file(ctx["file"]["id"])
    return ctx


def setup_closed_file_with_released_lien(amount_cents=500_000,
                                         quoted_payoff_cents=500_000,
                                         purchase_price_cents=250_000_000,
                                         annual_fee=0, **kwargs):
    """CLOSED file that carried one lien to RELEASED before funding and closing."""
    file_overrides = dict(kwargs.pop("file_overrides", {}) or {})
    file_overrides.setdefault("purchase_price_cents", purchase_price_cents)
    file_overrides.setdefault("annual_registration_fee_cents", annual_fee)
    ctx = setup_lien_released(
        amount_cents=amount_cents, quoted_payoff_cents=quoted_payoff_cents,
        file_overrides=file_overrides, **kwargs,
    )
    ctx["file"] = fund_file_to_due(ctx["file"]["id"], ctx["buyer"]["id"])
    ctx["file"] = close_escrow_file(ctx["file"]["id"])
    assert ctx["file"]["status"] == "CLOSED"
    return ctx


# ── Tier 5: post-close helpers ───────────────────────────────────────

def queue_and_submit_filing(file_id, filing_type):
    filing = create_filing(file_id, filing_type)
    return submit_filing(filing["id"])


def setup_accepted_filing(file_id, filing_type, confirmation_code):
    filing = queue_and_submit_filing(file_id, filing_type)
    return accept_filing(filing["id"], confirmation_code)


def create_sent_document(file_id, doc_type, required_signer_party_ids):
    doc = create_document(file_id, doc_type, required_signer_party_ids)
    return send_document(doc["id"])
