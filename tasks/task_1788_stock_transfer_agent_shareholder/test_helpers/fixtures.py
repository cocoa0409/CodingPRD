"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Shareholder calls are entity-backed by ShareholderAccount
and IssuerOfficer calls are entity-backed by Issuer. Ownership-gated calls
always build headers from the real entity id via make_shareholder_headers /
make_issuer_officer_headers — never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_LOSS_DATE,
    DEFAULT_PAYABLE_DATE,
    DEFAULT_RECORD_DATE,
)
from .factories import (
    create_account_payload,
    create_issuer_payload,
    create_position_payload,
    declaration_payload,
    deficiency_payload,
    freeze_window_payload,
    inquiry_payload,
    legend_request_payload,
    medallion_payload,
    opinion_payload,
    post_bond_payload,
    report_lost_payload,
    transfer_request_payload,
    withdrawal_payload,
)
from .test_users import (
    TEST_USERS,
    make_examiner_headers,
    make_issuer_officer_headers,
    make_shareholder_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["agent_admin_headers"]
EXAMINER = TEST_USERS["transfer_examiner_headers"]      # opaque id "exam_1"
SUPERVISOR = TEST_USERS["transfer_supervisor_headers"]  # opaque id "sup_1"
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SERVICE = TEST_USERS["service_agent_headers"]           # opaque id "agent_1"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and reads
# ---------------------------------------------------------------------------

def create_issuer(name="Acme Corp", cusip="000000001", ticker="ACME",
                  shares_outstanding=100, par_value_cents=1,
                  current_market_price_cents=5000) -> dict:
    """Onboard an issuer (born ACTIVE, version 1). Returns the issuer."""
    payload = create_issuer_payload(
        name=name, cusip=cusip, ticker=ticker,
        shares_outstanding=shares_outstanding, par_value_cents=par_value_cents,
        current_market_price_cents=current_market_price_cents,
    )
    return get_success_data(api_client.create_issuer(payload, ADMIN))


def officer_headers(issuer) -> dict:
    """Entity-backed IssuerOfficer headers for the given issuer."""
    return make_issuer_officer_headers(issuer["id"])


def create_account(holder_name="Test Holder", state_code="OK", city="Tulsa",
                   postal_code="74101", address_line1="1 Main St",
                   country_code="US", tax_id="000-00-0000",
                   tin_status=None, residency=None, treaty_tier=None) -> dict:
    """Register a shareholder account (born ACTIVE, version 1)."""
    payload = create_account_payload(
        holder_name=holder_name, state_code=state_code, city=city,
        postal_code=postal_code, address_line1=address_line1,
        country_code=country_code, tax_id=tax_id,
    )
    if tin_status is not None:
        payload["tin_status"] = tin_status
    if residency is not None:
        payload["residency"] = residency
    if treaty_tier is not None:
        payload["treaty_tier"] = treaty_tier
    return get_success_data(api_client.create_account(payload, ADMIN))


def get_account(account_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_account(account_id, headers))


def get_issuer(issuer_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_issuer(issuer_id, headers))


def patch_issuer(issuer, payload) -> dict:
    return get_success_data(
        api_client.patch_issuer(issuer["id"], payload, officer_headers(issuer)))


def patch_account(account_id, payload, headers=ADMIN) -> dict:
    return get_success_data(api_client.patch_account(account_id, payload, headers))


def seed_position(account_id, issuer_id, book_entry_shares,
                  restricted_shares=None) -> dict:
    """Seed the registered-holder position (born ACTIVE, version 1)."""
    payload = create_position_payload(issuer_id, book_entry_shares)
    if restricted_shares is not None:
        payload["restricted_shares"] = restricted_shares
    return get_success_data(api_client.create_position(account_id, payload, ADMIN))


def get_position(account_id, issuer_id, headers=ADMIN) -> dict:
    """Read the single position for an (account, issuer) pair."""
    data, _ = validate_paginated(api_client.list_positions(
        headers, params={"account_id": account_id, "issuer_id": issuer_id}))
    assert len(data) == 1, f"expected exactly one position, got {len(data)}"
    return data[0]


def set_clock(to_iso8601) -> dict:
    """Advance the logical clock; evaluates every time-gated transition."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def scan_dormancy() -> dict:
    """Run the dormancy sweep. Returns {accounts_marked_dormant, cases_created}."""
    return get_success_data(api_client.scan_escheatment(ADMIN))


def create_declaration(issuer, record_date=DEFAULT_RECORD_DATE,
                       payable_date=DEFAULT_PAYABLE_DATE,
                       amount_per_share_millicents=500) -> dict:
    payload = declaration_payload(issuer["id"], record_date=record_date,
                                  payable_date=payable_date,
                                  amount_per_share_millicents=amount_per_share_millicents)
    return get_success_data(
        api_client.create_dividend_declaration(payload, officer_headers(issuer)))


def get_declaration(declaration_id, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.get_dividend_declaration(declaration_id, headers))


def list_payments(declaration_id=None, account_id=None, status=None,
                  headers=ADMIN) -> list:
    params = {}
    if declaration_id is not None:
        params["declaration_id"] = declaration_id
    if account_id is not None:
        params["account_id"] = account_id
    if status is not None:
        params["status"] = status
    data, _ = validate_paginated(api_client.list_dividend_payments(headers, params))
    return data


def single_payment(declaration_id, headers=ADMIN) -> dict:
    payments = list_payments(declaration_id=declaration_id, headers=headers)
    assert len(payments) == 1, f"expected one payment, got {len(payments)}"
    return payments[0]


def list_cases(account_id=None, status=None, headers=COMPLIANCE) -> list:
    params = {}
    if account_id is not None:
        params["account_id"] = account_id
    if status is not None:
        params["status"] = status
    data, _ = validate_paginated(api_client.list_escheatment_cases(headers, params))
    return data


def single_case(account_id, headers=COMPLIANCE) -> dict:
    cases = list_cases(account_id=account_id, headers=headers)
    assert len(cases) == 1, f"expected one case, got {len(cases)}"
    return cases[0]


def get_case(case_id, headers=COMPLIANCE) -> dict:
    return get_success_data(api_client.get_escheatment_case(case_id, headers))


def send_notice(case_id) -> dict:
    return get_success_data(api_client.send_case_notice(case_id, COMPLIANCE))


def report_case(case_id) -> dict:
    return get_success_data(api_client.report_case(case_id, COMPLIANCE))


def remit_case(case_id) -> dict:
    return get_success_data(api_client.remit_case(case_id, COMPLIANCE))


def reactivate_case(case_id, agent_id="agent_1") -> dict:
    from .test_users import make_service_agent_headers
    return get_success_data(
        api_client.reactivate_case(case_id, make_service_agent_headers(agent_id)))


# ---------------------------------------------------------------------------
# Tier 1: certificates and claims
# ---------------------------------------------------------------------------

def withdraw_certificate(position_id, share_quantity, examiner_id="exam_1",
                         legend_restricted=None) -> dict:
    payload = withdrawal_payload(share_quantity)
    if legend_restricted is not None:
        payload["legend_restricted"] = legend_restricted
    return get_success_data(api_client.withdraw_certificate(
        position_id, payload, make_examiner_headers(examiner_id)))


def report_lost(certificate_id, loss_date=DEFAULT_LOSS_DATE,
                examiner_id="exam_1") -> dict:
    """Report a certificate lost; returns the created FILED claim."""
    return get_success_data(api_client.report_lost(
        certificate_id, report_lost_payload(loss_date),
        make_examiner_headers(examiner_id)))


def recover_certificate(certificate_id, examiner_id="exam_1") -> dict:
    return get_success_data(
        api_client.recover_certificate(certificate_id,
                                       make_examiner_headers(examiner_id)))


def post_bond(claim_id, bond_variant, premium_paid_cents,
              examiner_id="exam_1") -> dict:
    return get_success_data(api_client.post_bond(
        claim_id, post_bond_payload(bond_variant, premium_paid_cents),
        make_examiner_headers(examiner_id)))


def approve_claim(claim_id, supervisor_id="sup_1") -> dict:
    return get_success_data(
        api_client.approve_claim(claim_id, make_supervisor_headers(supervisor_id)))


def get_claim(claim_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers))


def list_claims(certificate_id=None, status=None, headers=ADMIN) -> list:
    params = {}
    if certificate_id is not None:
        params["certificate_id"] = certificate_id
    if status is not None:
        params["status"] = status
    data, _ = validate_paginated(api_client.list_claims(headers, params))
    return data


def get_certificate_for_account(account_id, certificate_id, headers=ADMIN) -> dict:
    data, _ = validate_paginated(
        api_client.list_certificates(headers, {"account_id": account_id}))
    for cert in data:
        if cert["id"] == certificate_id:
            return cert
    raise AssertionError(f"certificate {certificate_id} not found for {account_id}")


# ---------------------------------------------------------------------------
# Tier 1: transfer requests
# ---------------------------------------------------------------------------

def create_transfer(from_account_id, to_account_id, issuer_id, share_quantity,
                    source_certificate_id=None, examiner_id="exam_1") -> dict:
    """Create a transfer request, threading the OCC token from a fresh read of
    the transferor account. Returns the UNDER_REVIEW request."""
    account = get_account(from_account_id)
    payload = transfer_request_payload(
        from_account_id, to_account_id, issuer_id, share_quantity,
        expected_account_version=account["version"],
        source_certificate_id=source_certificate_id,
    )
    return get_success_data(api_client.create_transfer_request(
        payload, make_examiner_headers(examiner_id)))


def get_transfer(transfer_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_transfer_request(transfer_id, headers))


def list_transfers(from_account_id=None, status=None, headers=ADMIN) -> list:
    params = {}
    if from_account_id is not None:
        params["from_account_id"] = from_account_id
    if status is not None:
        params["status"] = status
    data, _ = validate_paginated(api_client.list_transfer_requests(headers, params))
    return data


def submit_medallion(transfer_id, coverage_cents, examiner_id="exam_1",
                     medallion_reference="MED-1") -> dict:
    return get_success_data(api_client.submit_medallion(
        transfer_id, medallion_payload(medallion_reference, coverage_cents),
        make_examiner_headers(examiner_id)))


def flag_deficient(transfer_id, reason="paperwork deficient",
                   examiner_id="exam_1") -> dict:
    return get_success_data(api_client.flag_transfer_deficient(
        transfer_id, deficiency_payload(reason), make_examiner_headers(examiner_id)))


def cure_deficiency(transfer_id, examiner_id="exam_1") -> dict:
    return get_success_data(api_client.cure_transfer_deficiency(
        transfer_id, make_examiner_headers(examiner_id)))


def approve_transfer(transfer_id, supervisor_id="sup_1") -> dict:
    return get_success_data(api_client.approve_transfer_request(
        transfer_id, make_supervisor_headers(supervisor_id)))


def settle_transfer(transfer_id, supervisor_id="sup_1") -> dict:
    return get_success_data(api_client.settle_transfer_request(
        transfer_id, make_supervisor_headers(supervisor_id)))


# ---------------------------------------------------------------------------
# Tier 1: legend-removal requests and inquiries
# ---------------------------------------------------------------------------

def create_legend_request(position_id, account_id, share_quantity,
                          acquisition_date, rule_basis="RULE_144") -> dict:
    """Create a legend-removal request as the owning Shareholder, threading the
    OCC token from a fresh read of the position."""
    positions = validate_paginated(api_client.list_positions(
        ADMIN, {"account_id": account_id}))[0]
    current = next(p for p in positions if p["id"] == position_id)
    payload = legend_request_payload(
        position_id, account_id, share_quantity, acquisition_date,
        expected_position_version=current["version"], rule_basis=rule_basis)
    return get_success_data(api_client.create_legend_request(
        payload, make_shareholder_headers(account_id)))


def get_legend_request(request_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_legend_request(request_id, headers))


def submit_opinion(request_id, account_id=None,
                   counsel_opinion_reference="OP-1") -> dict:
    """Submit counsel opinion as the owning Shareholder (or ComplianceOfficer
    when account_id is None)."""
    headers = (make_shareholder_headers(account_id) if account_id is not None
               else COMPLIANCE)
    return get_success_data(api_client.submit_opinion(
        request_id, opinion_payload(counsel_opinion_reference), headers))


def flag_legend_deficient(request_id, reason="opinion deficient") -> dict:
    return get_success_data(api_client.flag_legend_deficient(
        request_id, deficiency_payload(reason), COMPLIANCE))


def approve_legend(request_id) -> dict:
    return get_success_data(api_client.approve_legend_request(request_id, COMPLIANCE))


def create_inquiry(account_id, channel="EMAIL", subject="question") -> dict:
    return get_success_data(api_client.create_inquiry(
        inquiry_payload(account_id, channel, subject),
        make_shareholder_headers(account_id)))


def get_inquiry(inquiry_id, headers=SERVICE) -> dict:
    return get_success_data(api_client.get_inquiry(inquiry_id, headers))


def claim_inquiry(inquiry_id, agent_id="agent_1") -> dict:
    from .test_users import make_service_agent_headers
    return get_success_data(
        api_client.claim_inquiry(inquiry_id, make_service_agent_headers(agent_id)))


def answer_inquiry(inquiry_id, answer_text="answer", agent_id="agent_1") -> dict:
    from .test_users import make_service_agent_headers
    return get_success_data(api_client.answer_inquiry(
        inquiry_id, {"answer_text": answer_text},
        make_service_agent_headers(agent_id)))


def create_freeze_window(issuer, start_date, end_date, reason="freeze") -> dict:
    return get_success_data(api_client.create_freeze_window(
        issuer["id"], freeze_window_payload(start_date, end_date, reason),
        officer_headers(issuer)))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_issuer_account_position(shares_outstanding=100, price_cents=5000,
                                  book_entry_shares=100, restricted_shares=None,
                                  state_code="OK", tin_status="CERTIFIED",
                                  holder_name="Test Holder", cusip="000000001",
                                  issuer_name="Acme Corp", ticker="ACME") -> dict:
    """Issuer + one account + its seeded position. Returns a ctx dict."""
    issuer = create_issuer(name=issuer_name, cusip=cusip, ticker=ticker,
                           shares_outstanding=shares_outstanding,
                           current_market_price_cents=price_cents)
    account = create_account(holder_name=holder_name, state_code=state_code,
                             tin_status=tin_status)
    position = seed_position(account["id"], issuer["id"], book_entry_shares,
                             restricted_shares)
    return {"issuer": issuer, "account": account, "position": position}


def setup_transfer_pair(shares_outstanding=500, price_cents=5000,
                        book_entry_shares=500, share_quantity=100,
                        state_code="CA") -> dict:
    """Issuer + transferor (seeded) + transferee + one UNDER_REVIEW DRS
    transfer. Returns ctx with issuer/acct_a/acct_b/transfer."""
    issuer = create_issuer(shares_outstanding=shares_outstanding,
                           current_market_price_cents=price_cents)
    acct_a = create_account(holder_name="Frank From", state_code=state_code,
                            tin_status="CERTIFIED")
    acct_b = create_account(holder_name="Gina To", state_code=state_code,
                            tin_status="CERTIFIED", tax_id="000-00-0001")
    seed_position(acct_a["id"], issuer["id"], book_entry_shares)
    transfer = create_transfer(acct_a["id"], acct_b["id"], issuer["id"],
                               share_quantity)
    return {"issuer": issuer, "acct_a": acct_a, "acct_b": acct_b,
            "transfer": transfer}


def setup_medallion_verified_transfer(share_quantity=10, price_cents=5000,
                                      book_entry_shares=100,
                                      shares_outstanding=100,
                                      examiner_id="exam_1") -> dict:
    """UNDER_REVIEW -> MEDALLION_VERIFIED with coverage exactly at value."""
    ctx = setup_transfer_pair(shares_outstanding=shares_outstanding,
                              price_cents=price_cents,
                              book_entry_shares=book_entry_shares,
                              share_quantity=share_quantity, state_code="OK")
    coverage = share_quantity * price_cents
    ctx["transfer"] = submit_medallion(ctx["transfer"]["id"], coverage,
                                       examiner_id=examiner_id)
    return ctx


def setup_approved_transfer(share_quantity=40, price_cents=5000,
                            book_entry_shares=100, shares_outstanding=100,
                            examiner_id="exam_1", supervisor_id="sup_1") -> dict:
    """DRS transfer walked to APPROVED."""
    ctx = setup_medallion_verified_transfer(
        share_quantity=share_quantity, price_cents=price_cents,
        book_entry_shares=book_entry_shares,
        shares_outstanding=shares_outstanding, examiner_id=examiner_id)
    ctx["transfer"] = approve_transfer(ctx["transfer"]["id"], supervisor_id)
    return ctx


def setup_approved_certificated_transfer(shares_outstanding=300,
                                         price_cents=5000, book_entry_shares=300,
                                         cert_shares=200, examiner_id="exam_1",
                                         supervisor_id="sup_1") -> dict:
    """Certificated-source transfer walked to APPROVED: the source certificate
    covers the whole transfer quantity. Returns ctx incl. certificate."""
    issuer = create_issuer(shares_outstanding=shares_outstanding,
                           current_market_price_cents=price_cents)
    acct_a = create_account(holder_name="Ivy Source", state_code="CA",
                            tin_status="CERTIFIED")
    acct_b = create_account(holder_name="Jack Dest", state_code="NV",
                            tin_status="CERTIFIED", tax_id="000-00-0002")
    position = seed_position(acct_a["id"], issuer["id"], book_entry_shares)
    certificate = withdraw_certificate(position["id"], cert_shares, examiner_id)
    transfer = create_transfer(acct_a["id"], acct_b["id"], issuer["id"],
                               cert_shares, source_certificate_id=certificate["id"],
                               examiner_id=examiner_id)
    transfer = submit_medallion(transfer["id"], cert_shares * price_cents,
                                examiner_id=examiner_id)
    transfer = approve_transfer(transfer["id"], supervisor_id)
    return {"issuer": issuer, "acct_a": acct_a, "acct_b": acct_b,
            "position": position, "certificate": certificate,
            "transfer": transfer}


# ---------------------------------------------------------------------------
# Tier 2: lost certificates and bonds
# ---------------------------------------------------------------------------

def setup_lost_claim(price_cents=5000, shares_outstanding=300,
                     book_entry_shares=300, cert_shares=100,
                     loss_date=DEFAULT_LOSS_DATE, examiner_id="exam_1") -> dict:
    """Issuer + account + position + one withdrawn certificate reported lost.
    Returns ctx with issuer/account/position/certificate/claim (FILED)."""
    ctx = setup_issuer_account_position(
        shares_outstanding=shares_outstanding, price_cents=price_cents,
        book_entry_shares=book_entry_shares, state_code="CA",
        holder_name="Uma Loser")
    certificate = withdraw_certificate(ctx["position"]["id"], cert_shares,
                                       examiner_id)
    claim = report_lost(certificate["id"], loss_date, examiner_id)
    ctx.update({"certificate": certificate, "claim": claim})
    return ctx


def setup_bond_posted_claim(bond_variant="FIXED_PENALTY", premium_paid_cents=30000,
                            **kwargs) -> dict:
    """Lost claim walked to BOND_POSTED."""
    ctx = setup_lost_claim(**kwargs)
    ctx["claim"] = post_bond(ctx["claim"]["id"], bond_variant,
                             premium_paid_cents)
    return ctx


def setup_two_lost_certs_price_moved() -> dict:
    """Two 100-share certificates from one 300-share position; the first
    reported lost at price 5000, then the market moves to 7000 and the second
    is reported lost. Returns ctx with cert1/cert2/claim1/claim2."""
    issuer = create_issuer(name="Acme Corp", cusip="000000001", ticker="ACME",
                           shares_outstanding=300,
                           current_market_price_cents=5000)
    account = create_account(holder_name="Alice Holder", state_code="CA",
                             city="Los Angeles", postal_code="90001",
                             tin_status="CERTIFIED", tax_id="111-22-3333")
    position = seed_position(account["id"], issuer["id"], 300)
    cert1 = withdraw_certificate(position["id"], 100)
    cert2 = withdraw_certificate(position["id"], 100)
    claim1 = report_lost(cert1["id"], "2026-08-05T00:00:00Z", "exam_1")
    patch_issuer(issuer, {"current_market_price_cents": 7000})
    claim2 = report_lost(cert2["id"], "2026-08-06T00:00:00Z", "exam_1")
    return {"issuer": issuer, "account": account, "position": position,
            "cert1": cert1, "cert2": cert2, "claim1": claim1, "claim2": claim2}


# ---------------------------------------------------------------------------
# Tier 3: dividend lifecycle
# ---------------------------------------------------------------------------

def setup_disbursed_payment(shares=100, millicents=500, tin_status="CERTIFIED",
                            state_code="OK", price_cents=5000,
                            record_date="2026-08-02T00:00:00Z",
                            payable_date="2026-08-03T00:00:00Z",
                            residency=None, treaty_tier=None,
                            holder_name="Payee Pat",
                            single_clock_set=False) -> dict:
    """Issuer + account + position + declaration; clock driven to record date
    then payable date so the single generated payment is DISBURSED.
    With single_clock_set=True, one clock set past both dates performs the
    accrual and disbursement in a single evaluation."""
    issuer = create_issuer(shares_outstanding=shares,
                           current_market_price_cents=price_cents)
    account = create_account(holder_name=holder_name, state_code=state_code,
                             tin_status=tin_status, residency=residency,
                             treaty_tier=treaty_tier)
    position = seed_position(account["id"], issuer["id"], shares)
    declaration = create_declaration(issuer, record_date=record_date,
                                     payable_date=payable_date,
                                     amount_per_share_millicents=millicents)
    if single_clock_set:
        set_clock(payable_date)
    else:
        set_clock(record_date)
        set_clock(payable_date)
    payment = single_payment(declaration["id"])
    return {"issuer": issuer, "account": account, "position": position,
            "declaration": declaration, "payment": payment}


def setup_returned_payment(**kwargs) -> dict:
    """A DISBURSED payment marked undeliverable (address_verified now false)."""
    ctx = setup_disbursed_payment(**kwargs)
    returned = get_success_data(
        api_client.mark_payment_returned(ctx["payment"]["id"], SERVICE))
    ctx["payment"] = returned
    return ctx


def setup_w9_cure_payment() -> dict:
    """MISSING-tin payment accrued at record date, then the holder certifies
    the TIN before the payable date. Payment ends DISBURSED."""
    issuer = create_issuer(name="Beta Inc", cusip="000000002", ticker="BETA",
                           shares_outstanding=1000)
    account = create_account(holder_name="Bob Uncertified", state_code="TX",
                             city="Austin", postal_code="73301",
                             tax_id="222-33-4444", tin_status="MISSING")
    seed_position(account["id"], issuer["id"], 1000)
    declaration = create_declaration(issuer, record_date="2026-09-01T00:00:00Z",
                                     payable_date="2026-09-15T00:00:00Z",
                                     amount_per_share_millicents=500)
    set_clock("2026-09-01T00:00:00Z")
    patch_account(account["id"], {"tin_status": "CERTIFIED"})
    set_clock("2026-09-15T00:00:00Z")
    payment = single_payment(declaration["id"])
    return {"issuer": issuer, "account": account, "declaration": declaration,
            "payment": payment}


def setup_two_share_667_declaration() -> dict:
    """Two CERTIFIED US accounts with exactly 1 share each, against one
    declaration of 667 millicents per share; clock driven to the record date."""
    issuer = create_issuer(name="Gamma LLC", cusip="000000003", ticker="GAMA",
                           shares_outstanding=2)
    acct1 = create_account(holder_name="Carol One", state_code="NY",
                           city="Albany", postal_code="12201",
                           tax_id="333-44-5555", tin_status="CERTIFIED")
    acct2 = create_account(holder_name="Dave Two", state_code="NY",
                           city="Albany", postal_code="12201",
                           tax_id="444-55-6666", tin_status="CERTIFIED",
                           address_line1="4 Elm St")
    seed_position(acct1["id"], issuer["id"], 1)
    seed_position(acct2["id"], issuer["id"], 1)
    declaration = create_declaration(issuer, record_date="2026-09-01T00:00:00Z",
                                     payable_date="2026-09-15T00:00:00Z",
                                     amount_per_share_millicents=667)
    set_clock("2026-09-01T00:00:00Z")
    payments = list_payments(declaration["id"])
    return {"issuer": issuer, "acct1": acct1, "acct2": acct2,
            "declaration": declaration, "payments": payments}


def setup_mixed_residency_payments() -> dict:
    """One declaration, two holders: FOREIGN/CERTIFIED/TREATY (2000 shares)
    and US/MISSING (1000 shares); clock driven past the payable date."""
    issuer = create_issuer(name="Delta Co", cusip="000000004", ticker="DLTA",
                           shares_outstanding=3000)
    acct_f = create_account(holder_name="Foreign Treaty", state_code="NY",
                            city="Paris", postal_code="75002",
                            address_line1="5 Rue de Paix", country_code="FR",
                            residency="FOREIGN", tax_id="FR-123",
                            tin_status="CERTIFIED", treaty_tier="TREATY")
    acct_m = create_account(holder_name="Mary Missing", state_code="TX",
                            city="Houston", postal_code="77001",
                            address_line1="6 Birch St", tax_id="555-66-7777",
                            tin_status="MISSING")
    seed_position(acct_f["id"], issuer["id"], 2000)
    seed_position(acct_m["id"], issuer["id"], 1000)
    declaration = create_declaration(issuer, record_date="2026-09-01T00:00:00Z",
                                     payable_date="2026-09-15T00:00:00Z",
                                     amount_per_share_millicents=500)
    set_clock("2026-09-01T00:00:00Z")
    set_clock("2026-09-15T00:00:00Z")
    pay_f = list_payments(declaration["id"], account_id=acct_f["id"])[0]
    pay_m = list_payments(declaration["id"], account_id=acct_m["id"])[0]
    return {"issuer": issuer, "acct_f": acct_f, "acct_m": acct_m,
            "declaration": declaration, "pay_f": pay_f, "pay_m": pay_m}


def setup_suspended_issuer_declaration() -> dict:
    """Declaration created while ACTIVE, then the issuer is SUSPENDED before
    the record date."""
    ctx = setup_issuer_account_position(shares_outstanding=100,
                                        book_entry_shares=100,
                                        holder_name="Tina Holder",
                                        state_code="CA")
    declaration = create_declaration(
        ctx["issuer"], record_date="2026-09-01T00:00:00Z",
        payable_date="2026-09-15T00:00:00Z", amount_per_share_millicents=500)
    patch_issuer(ctx["issuer"], {"status": "SUSPENDED"})
    ctx["declaration"] = declaration
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: dormancy and escheatment pipelines
# ---------------------------------------------------------------------------

def setup_dormant_account_with_case(state_code="CA", shares=5, price_cents=5000,
                                    sweep_date="2029-08-01T00:00:00Z",
                                    holder_name="Dormant Dan") -> dict:
    """Account created at the default clock, clock advanced past its dormancy
    horizon, swept: account DORMANT with one IDENTIFIED case."""
    ctx = setup_issuer_account_position(shares_outstanding=shares,
                                        price_cents=price_cents,
                                        book_entry_shares=shares,
                                        state_code=state_code,
                                        holder_name=holder_name)
    set_clock(sweep_date)
    ctx["scan"] = scan_dormancy()
    ctx["case"] = single_case(ctx["account"]["id"])
    return ctx


def setup_reactivated_case() -> dict:
    """CA account swept dormant at its 3-year anniversary (2029-08-01), then
    reactivated by a ServiceAgent: case REACTIVATED, account ACTIVE."""
    ctx = setup_dormant_account_with_case(state_code="CA", shares=5,
                                          holder_name="Hank Cyclic")
    ctx["case"] = reactivate_case(ctx["case"]["id"])
    ctx["account"] = get_account(ctx["account"]["id"])
    return ctx


def setup_report_ready_case() -> dict:
    """Full pipeline to NOTICE_SENT with the 60-day notice window elapsed:
    TX account with 10 shares of a 6000-cent issuer; a 250-gross payment
    disbursed 2026-08-03 and stale-dated by the 2029-08-01 clock; swept,
    noticed, clock at 2029-09-30 (notice + 60 days)."""
    issuer = create_issuer(name="Epsilon Inc", cusip="000000005", ticker="EPSI",
                           shares_outstanding=10,
                           current_market_price_cents=6000)
    account = create_account(holder_name="Eddie Dormant", state_code="TX",
                             city="Dallas", postal_code="75201",
                             tax_id="666-77-8888", tin_status="CERTIFIED")
    position = seed_position(account["id"], issuer["id"], 10)
    declaration = create_declaration(
        issuer, record_date="2026-08-02T00:00:00Z",
        payable_date="2026-08-03T00:00:00Z", amount_per_share_millicents=25000)
    set_clock("2026-08-02T00:00:00Z")
    set_clock("2026-08-03T00:00:00Z")
    set_clock("2029-08-01T00:00:00Z")
    scan_dormancy()
    case = single_case(account["id"])
    case = send_notice(case["id"])
    set_clock("2029-09-30T00:00:00Z")
    payment = single_payment(declaration["id"])
    return {"issuer": issuer, "account": account, "position": position,
            "declaration": declaration, "payment": payment, "case": case}


def setup_reported_case() -> dict:
    """Report-ready pipeline driven one step further: case REPORTED with the
    valuation frozen."""
    ctx = setup_report_ready_case()
    ctx["case"] = report_case(ctx["case"]["id"])
    return ctx


def setup_ca_dormancy_pair() -> dict:
    """Two CA accounts created one day apart (2026-08-01 and 2026-08-02),
    each holding 1 share."""
    issuer = create_issuer(name="Nu Corp", cusip="000000013", ticker="NUCO",
                           shares_outstanding=2)
    c1 = create_account(holder_name="Pat Early", state_code="CA",
                        city="Bakersfield", postal_code="93301",
                        tax_id="010-10-1010", tin_status="CERTIFIED")
    seed_position(c1["id"], issuer["id"], 1)
    set_clock("2026-08-02T00:00:00Z")
    c2 = create_account(holder_name="Quinn Late", state_code="CA",
                        city="Bakersfield", postal_code="93302",
                        tax_id="111-11-1112", tin_status="CERTIFIED",
                        address_line1="21 Redwood St")
    seed_position(c2["id"], issuer["id"], 1)
    return {"issuer": issuer, "c1": c1, "c2": c2}
