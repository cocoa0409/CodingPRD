"""Composite setup helpers for the E-Rate funding workflows (PRD §3).

Every helper builds preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server (empty database) before each test.
Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" assertion, not a confusing downstream error.

Context convention: composite builders return a plain dict ("ctx") whose keys
name the created resources — cycle, applicant, snapshot, u_coord,
coord_headers, u_cert, cert_headers, provider, vendor_headers, posting, bids,
contract, request, lines, services. Entity-backed headers are always threaded
from the created entity's id (never a shared constant) so ownership checks
pass.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DATES
from .factories import (
    create_appeal_payload,
    create_applicant_payload,
    create_applicant_user_payload,
    create_bid_payload,
    create_contract_payload,
    create_eligible_service_payload,
    create_funding_cycle_payload,
    create_funding_request_line_payload,
    create_funding_request_payload,
    create_invoice_submission_payload,
    create_nslp_snapshot_payload,
    create_procurement_posting_payload,
    create_service_provider_payload,
    create_service_substitution_payload,
)
from .test_users import (
    TEST_USERS,
    make_appeal_officer_headers,
    make_auditor_headers,
    make_certifier_headers,
    make_commitment_officer_headers,
    make_coordinator_headers,
    make_invoice_processor_headers,
    make_pia_reviewer_headers,
    make_vendor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
READER = TEST_USERS["program_admin_headers"]  # read endpoints accept any role
DEFAULT_REVIEWER_ID = "usac-emp-9"
DEFAULT_OFFICER_ID = "usac-emp-7"
DEFAULT_PROCESSOR_ID = "usac-inv-1"
DEFAULT_APPEAL_OFFICER_ID = "usac-app-3"
DEFAULT_AUDITOR_ID = "usac-aud-1"


def _ok(resp, step: str):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed at {step}: {resp.status_code} {resp.text}"
    return data


def _ok_list(resp, step: str):
    data = get_success_data(resp)
    assert isinstance(data, list), f"Setup failed at {step}: {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Granular creators (Tier 0)
# ---------------------------------------------------------------------------

def set_clock(iso: str):
    """Advance the logical clock (PRD §2.4). Returns {current_utc}."""
    return _ok(api_client.set_clock({"to_iso8601": iso}, ADMIN), "set_clock")


def new_cycle(label=DATES["CYCLE_LABEL"], **overrides) -> dict:
    payload = create_funding_cycle_payload(label=label, **overrides)
    return _ok(api_client.create_funding_cycle(payload, ADMIN), "create_funding_cycle")


def new_applicant(**overrides) -> dict:
    return _ok(api_client.create_applicant(create_applicant_payload(**overrides), ADMIN),
               "create_applicant")


def new_applicant_user(applicant_id, display_name="Casey Coordinator",
                       function="COORDINATOR") -> dict:
    payload = create_applicant_user_payload(
        applicant_id=applicant_id, display_name=display_name, function=function
    )
    return _ok(api_client.create_applicant_user(payload, ADMIN), "create_applicant_user")


def new_applicant_user_with_headers(applicant_id, display_name="Casey Coordinator",
                                    function="COORDINATOR"):
    """Create the ApplicantUser and return (user, ownership-correct headers)."""
    user = new_applicant_user(applicant_id, display_name, function)
    if function == "CERTIFIER":
        return user, make_certifier_headers(user["id"])
    return user, make_coordinator_headers(user["id"])


def new_provider(name="VendorOne", spin="SPIN-001") -> dict:
    payload = create_service_provider_payload(name=name, spin=spin)
    return _ok(api_client.create_service_provider(payload, ADMIN), "create_service_provider")


def new_provider_with_headers(name="VendorOne", spin="SPIN-001"):
    provider = new_provider(name, spin)
    return provider, make_vendor_headers(provider["id"])


def new_service(cycle_id, service_description="Dedicated Internet Access 1Gbps",
                category="CATEGORY_ONE", service_type="INTERNET_ACCESS") -> dict:
    payload = create_eligible_service_payload(
        funding_cycle_id=cycle_id, service_description=service_description,
        category=category, service_type=service_type,
    )
    return _ok(api_client.create_eligible_service(payload, ADMIN), "create_eligible_service")


def new_snapshot(applicant_id, cycle_id, **overrides) -> dict:
    payload = create_nslp_snapshot_payload(
        applicant_id=applicant_id, funding_cycle_id=cycle_id, **overrides
    )
    return _ok(api_client.create_nslp_snapshot(payload, ADMIN), "create_nslp_snapshot")


# ---------------------------------------------------------------------------
# Tier 1: applicant + program-year base
# ---------------------------------------------------------------------------

def setup_applicant_base(with_snapshot=True, snapshot_overrides=None,
                         applicant_overrides=None, cycle_label=DATES["CYCLE_LABEL"],
                         cycle_overrides=None) -> dict:
    """Funding cycle + applicant (+ optional NSLP snapshot) + coordinator and
    certifier ApplicantUsers with ownership-correct headers."""
    ctx = {}
    ctx["cycle"] = new_cycle(label=cycle_label, **(cycle_overrides or {}))
    ctx["applicant"] = new_applicant(**(applicant_overrides or {}))
    ctx["snapshot"] = (
        new_snapshot(ctx["applicant"]["id"], ctx["cycle"]["id"],
                     **(snapshot_overrides or {}))
        if with_snapshot else None
    )
    ctx["u_coord"], ctx["coord_headers"] = new_applicant_user_with_headers(
        ctx["applicant"]["id"], "Casey Coordinator", "COORDINATOR"
    )
    ctx["u_cert"], ctx["cert_headers"] = new_applicant_user_with_headers(
        ctx["applicant"]["id"], "Ceri Certifier", "CERTIFIER"
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: procurement (posting -> publish -> bids -> close -> award)
# ---------------------------------------------------------------------------

def new_posting(ctx, category="CATEGORY_ONE", description="Internet access",
                price_weight_pct=100, other_factor_weights=None) -> dict:
    payload = create_procurement_posting_payload(
        applicant_id=ctx["applicant"]["id"],
        funding_cycle_id=ctx["cycle"]["id"],
        category=category,
        description=description,
        price_weight_pct=price_weight_pct,
        other_factor_weights=list(other_factor_weights or []),
    )
    return _ok(api_client.create_procurement_posting(payload, ctx["coord_headers"]),
               "create_procurement_posting")


def publish_posting(ctx, posting) -> dict:
    return _ok(api_client.publish_posting(posting["id"], ctx["coord_headers"]),
               "publish_posting")


def submit_bid(ctx, posting, provider, eligible_price_cents, factor_scores=None,
               ineligible_price_cents=None) -> dict:
    payload = create_bid_payload(
        posting_id=posting["id"], eligible_price_cents=eligible_price_cents,
        factor_scores=list(factor_scores or []),
        ineligible_price_cents=ineligible_price_cents,
    )
    return _ok(api_client.create_bid(payload, make_vendor_headers(provider["id"])),
               "create_bid")


def qualify_bid(ctx, bid) -> dict:
    return _ok(api_client.qualify_bid(bid["id"], ctx["coord_headers"]), "qualify_bid")


def close_window(ctx, posting) -> dict:
    return _ok(api_client.close_posting_window(posting["id"], ctx["coord_headers"]),
               "close_posting_window")


def run_select_winner(ctx, posting, who="coord") -> dict:
    headers = ctx["coord_headers"] if who == "coord" else ctx["cert_headers"]
    return _ok(api_client.select_winner(posting["id"], headers), "select_winner")


def award_posting(ctx, posting, bid_specs, bid_clock=DATES["BID_CLOCK"],
                  close_clock=DATES["CLOSE_CLOCK"], selector="coord", qualify=True):
    """Submit + (optionally) qualify bids inside the half-open window, elapse
    the window, close it, and select the winner.

    bid_specs: list of dicts {provider, price, scores, qualify} — per-bid
    "qualify" defaults to the outer `qualify` flag.
    Returns the list of created bid dicts (in submission order).
    """
    set_clock(bid_clock)
    bids = []
    for spec in bid_specs:
        bid = submit_bid(ctx, posting, spec["provider"], spec["price"],
                         spec.get("scores"))
        if spec.get("qualify", qualify):
            bid = qualify_bid(ctx, bid)
        bids.append(bid)
    set_clock(close_clock)
    close_window(ctx, posting)
    run_select_winner(ctx, posting, who=selector)
    return bids


def setup_awarded_posting(category="CATEGORY_ONE", price_weight_pct=100,
                          other_factor_weights=None, bid_price=50000,
                          bid_scores=None, with_snapshot=True,
                          applicant_overrides=None, snapshot_overrides=None,
                          description="Internet access", selector="coord") -> dict:
    """Full procurement walk ending in an AWARDED posting with one qualified
    bid from one provider. Publishes at the startup-default clock."""
    ctx = setup_applicant_base(with_snapshot=with_snapshot,
                               applicant_overrides=applicant_overrides,
                               snapshot_overrides=snapshot_overrides)
    ctx["provider"], ctx["vendor_headers"] = new_provider_with_headers()
    ctx["posting"] = new_posting(ctx, category=category, description=description,
                                 price_weight_pct=price_weight_pct,
                                 other_factor_weights=other_factor_weights)
    publish_posting(ctx, ctx["posting"])
    ctx["bids"] = award_posting(
        ctx, ctx["posting"],
        [{"provider": ctx["provider"], "price": bid_price, "scores": bid_scores or []}],
        selector=selector,
    )
    ctx["posting"] = get_posting(ctx["posting"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: contracts
# ---------------------------------------------------------------------------

def new_contract(ctx, posting, bid, provider, category="CATEGORY_ONE",
                 total_eligible_cents=50000,
                 term=(DATES["CONTRACT_START"], DATES["CONTRACT_END"])) -> dict:
    payload = create_contract_payload(
        applicant_id=ctx["applicant"]["id"], service_provider_id=provider["id"],
        posting_id=posting["id"], winning_bid_id=bid["id"], category=category,
        total_eligible_cents=total_eligible_cents,
        service_start_date=term[0], service_end_date=term[1],
    )
    return _ok(api_client.create_contract(payload, ctx["coord_headers"]),
               "create_contract")


def certify_contract(ctx, contract, who="cert") -> dict:
    headers = ctx["cert_headers"] if who == "cert" else ctx["coord_headers"]
    return _ok(api_client.certify_contract(contract["id"], headers), "certify_contract")


def terminate_contract(ctx, contract, reason=None) -> dict:
    payload = {} if reason is None else {"reason": reason}
    return _ok(api_client.terminate_contract(contract["id"], payload, ctx["cert_headers"]),
               "terminate_contract")


def setup_certified_contract(category="CATEGORY_ONE", bid_price=50000,
                             contract_total=None, with_snapshot=True,
                             applicant_overrides=None, snapshot_overrides=None,
                             service_description=None, service_type=None,
                             extra_services=()) -> dict:
    """AWARDED posting + DRAFT contract + CERTIFIED. extra_services is a list
    of (description, category, service_type) tuples added to the same cycle
    inventory (for substitution scenarios)."""
    if service_type is None:
        service_type = ("INTERNAL_CONNECTIONS" if category == "CATEGORY_TWO"
                        else "INTERNET_ACCESS")
    if service_description is None:
        service_description = ("Wireless Access Points" if category == "CATEGORY_TWO"
                               else "Dedicated Internet Access 1Gbps")
    ctx = setup_awarded_posting(category=category, bid_price=bid_price,
                                with_snapshot=with_snapshot,
                                applicant_overrides=applicant_overrides,
                                snapshot_overrides=snapshot_overrides,
                                description="Competitive procurement")
    ctx["services"] = {
        "primary": new_service(ctx["cycle"]["id"], service_description,
                               category, service_type)
    }
    ctx["services"]["extra"] = [
        new_service(ctx["cycle"]["id"], desc, cat, stype)
        for desc, cat, stype in extra_services
    ]
    ctx["contract"] = new_contract(
        ctx, ctx["posting"], ctx["bids"][0], ctx["provider"], category=category,
        total_eligible_cents=contract_total if contract_total is not None else bid_price,
    )
    ctx["contract"] = certify_contract(ctx, ctx["contract"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: funding request lifecycle
# ---------------------------------------------------------------------------

def new_request(ctx) -> dict:
    payload = create_funding_request_payload(
        applicant_id=ctx["applicant"]["id"], funding_cycle_id=ctx["cycle"]["id"]
    )
    return _ok(api_client.create_funding_request(payload, ctx["coord_headers"]),
               "create_funding_request")


def new_line(ctx, request, contract, service, requested_pre_discount_cents) -> dict:
    payload = create_funding_request_line_payload(
        funding_request_id=request["id"], contract_id=contract["id"],
        eligible_service_id=service["id"],
        requested_pre_discount_cents=requested_pre_discount_cents,
    )
    return _ok(api_client.create_funding_request_line(payload, ctx["coord_headers"]),
               "create_funding_request_line")


def certify_request(ctx, request) -> dict:
    return _ok(api_client.certify_funding_request(request["id"], ctx["cert_headers"]),
               "certify_funding_request")


def begin_review(ctx, request, reviewer_id=DEFAULT_REVIEWER_ID) -> dict:
    return _ok(api_client.begin_review(request["id"],
                                       make_pia_reviewer_headers(reviewer_id)),
               "begin_review")


def request_info(ctx, request, info_request_text="Provide contract pages 4-7",
                 reviewer_id=DEFAULT_REVIEWER_ID) -> dict:
    return _ok(api_client.request_info(request["id"],
                                       {"info_request_text": info_request_text},
                                       make_pia_reviewer_headers(reviewer_id)),
               "request_info")


def pia_response(ctx, request, response_text, expected_request_version) -> dict:
    return _ok(api_client.submit_pia_response(
        request["id"],
        {"response_text": response_text,
         "expected_request_version": expected_request_version},
        ctx["coord_headers"]), "submit_pia_response")


def decide_request(ctx, request, outcome="COMMITTED", officer_id=DEFAULT_OFFICER_ID,
                   rationale=None) -> dict:
    payload = {"outcome": outcome}
    if rationale is not None:
        payload["rationale"] = rationale
    return _ok(api_client.decide_funding_request(
        request["id"], payload, make_commitment_officer_headers(officer_id)),
        "decide_funding_request")


def start_services(ctx, request) -> dict:
    return _ok(api_client.record_service_start(request["id"], ctx["coord_headers"]),
               "record_service_start")


def setup_request_with_lines(ctx, line_amounts=(50000,), service_key="primary",
                             certify=True, filing_clock=DATES["FILING_CLOCK"]) -> dict:
    """DRAFT request + one line per amount against ctx's certified contract and
    the chosen inventory service; optionally certified (FILED) at the filing
    clock. Lines are created in the given order (created_at ascending)."""
    set_clock(filing_clock)
    ctx["request"] = new_request(ctx)
    ctx["lines"] = [
        new_line(ctx, ctx["request"], ctx["contract"], ctx["services"][service_key], amt)
        for amt in line_amounts
    ]
    if certify:
        ctx["request"] = certify_request(ctx, ctx["request"])
    return ctx


def setup_committed_scenario(category="CATEGORY_ONE", bid_price=50000,
                             contract_total=None, line_amounts=(50000,),
                             with_snapshot=True, applicant_overrides=None,
                             snapshot_overrides=None, outcome="COMMITTED",
                             service_start=False,
                             filing_clock=DATES["FILING_CLOCK"],
                             decide_clock=None,
                             service_description=None, service_type=None,
                             extra_services=()) -> dict:
    """Full chain: certified contract -> request with lines -> certified
    (FILED) -> begin-review (PIA_REVIEW) -> decide (default COMMITTED);
    optionally records service start. Returns the rich ctx."""
    ctx = setup_certified_contract(
        category=category, bid_price=bid_price, contract_total=contract_total,
        with_snapshot=with_snapshot, applicant_overrides=applicant_overrides,
        snapshot_overrides=snapshot_overrides,
        service_description=service_description, service_type=service_type,
        extra_services=extra_services,
    )
    setup_request_with_lines(ctx, line_amounts=line_amounts,
                             filing_clock=filing_clock)
    ctx["request"] = begin_review(ctx, ctx["request"])
    if decide_clock is not None:
        set_clock(decide_clock)
    ctx["request"] = decide_request(ctx, ctx["request"], outcome=outcome)
    if service_start:
        ctx["request"] = start_services(ctx, ctx["request"])
    ctx["lines"] = [get_line(line["id"]) for line in ctx["lines"]]
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: invoicing
# ---------------------------------------------------------------------------

def new_bear_invoice(ctx, line, gross_invoiced_cents, applicant_paid_cents) -> dict:
    payload = create_invoice_submission_payload(
        frn_line_id=line["id"], method="BEAR",
        gross_invoiced_cents=gross_invoiced_cents,
        applicant_paid_cents=applicant_paid_cents,
    )
    return _ok(api_client.create_invoice_submission(payload, ctx["coord_headers"]),
               "create_invoice_submission(BEAR)")


def new_spi_invoice(ctx, line, gross_invoiced_cents, provider=None) -> dict:
    provider = provider or ctx["provider"]
    payload = create_invoice_submission_payload(
        frn_line_id=line["id"], method="SPI", gross_invoiced_cents=gross_invoiced_cents,
    )
    return _ok(api_client.create_invoice_submission(
        payload, make_vendor_headers(provider["id"])),
        "create_invoice_submission(SPI)")


def invoice_begin_review(invoice, processor_id=DEFAULT_PROCESSOR_ID) -> dict:
    return _ok(api_client.begin_invoice_review(
        invoice["id"], make_invoice_processor_headers(processor_id)),
        "begin_invoice_review")


def invoice_approve(invoice, processor_id=DEFAULT_PROCESSOR_ID) -> dict:
    return _ok(api_client.approve_invoice(
        invoice["id"], make_invoice_processor_headers(processor_id)), "approve_invoice")


def invoice_pay(invoice, processor_id=DEFAULT_PROCESSOR_ID) -> dict:
    return _ok(api_client.pay_invoice(
        invoice["id"], make_invoice_processor_headers(processor_id)), "pay_invoice")


def invoice_reject(invoice, rejection_reason, processor_id=DEFAULT_PROCESSOR_ID) -> dict:
    return _ok(api_client.reject_invoice(
        invoice["id"], {"rejection_reason": rejection_reason},
        make_invoice_processor_headers(processor_id)), "reject_invoice")


def invoice_resubmit_by_coordinator(ctx, invoice) -> dict:
    return _ok(api_client.resubmit_invoice(invoice["id"], ctx["coord_headers"]),
               "resubmit_invoice(BEAR)")


def invoice_resubmit_by_provider(invoice, provider) -> dict:
    return _ok(api_client.resubmit_invoice(
        invoice["id"], make_vendor_headers(provider["id"])), "resubmit_invoice(SPI)")


def set_audit_hold(ctx, active, auditor_id=DEFAULT_AUDITOR_ID) -> dict:
    return _ok(api_client.set_audit_hold(
        ctx["applicant"]["id"], {"active": active},
        make_auditor_headers(auditor_id)), "set_audit_hold")


# ---------------------------------------------------------------------------
# Tier 3: substitutions, appeals, retained documents
# ---------------------------------------------------------------------------

def new_substitution(ctx, line, to_service, expected_line_version,
                     supersedes_substitution_id=None, reason=None) -> dict:
    payload = create_service_substitution_payload(
        frn_line_id=line["id"], to_eligible_service_id=to_service["id"],
        expected_line_version=expected_line_version,
        supersedes_substitution_id=supersedes_substitution_id, reason=reason,
    )
    return _ok(api_client.create_service_substitution(payload, ctx["coord_headers"]),
               "create_service_substitution")


def approve_substitution(substitution) -> dict:
    return _ok(api_client.approve_substitution(substitution["id"], ADMIN),
               "approve_substitution")


def deny_substitution(substitution, denial_reason=None) -> dict:
    payload = {} if denial_reason is None else {"denial_reason": denial_reason}
    return _ok(api_client.deny_substitution(substitution["id"], payload, ADMIN),
               "deny_substitution")


def new_appeal(ctx, request, grounds="Appeal grounds") -> dict:
    payload = create_appeal_payload(funding_request_id=request["id"], grounds=grounds)
    return _ok(api_client.create_appeal(payload, ctx["coord_headers"]), "create_appeal")


def appeal_begin_review(appeal, officer_id=DEFAULT_APPEAL_OFFICER_ID) -> dict:
    return _ok(api_client.begin_appeal_review(
        appeal["id"], make_appeal_officer_headers(officer_id)), "begin_appeal_review")


def appeal_decide(appeal, outcome, rationale=None,
                  officer_id=DEFAULT_APPEAL_OFFICER_ID) -> dict:
    payload = {"outcome": outcome}
    if rationale is not None:
        payload["rationale"] = rationale
    return _ok(api_client.decide_appeal(
        appeal["id"], payload, make_appeal_officer_headers(officer_id)),
        "decide_appeal")


def list_documents(params) -> list:
    return _ok_list(api_client.list_retained_documents(READER, params=params),
                    "list_retained_documents")


def place_hold(document, hold_start_date, hold_end_date,
               auditor_id=DEFAULT_AUDITOR_ID) -> dict:
    return _ok(api_client.place_document_hold(
        document["id"],
        {"hold_start_date": hold_start_date, "hold_end_date": hold_end_date},
        make_auditor_headers(auditor_id)), "place_document_hold")


def release_hold(document, auditor_id=DEFAULT_AUDITOR_ID) -> dict:
    return _ok(api_client.release_document_hold(
        document["id"], make_auditor_headers(auditor_id)), "release_document_hold")


# ---------------------------------------------------------------------------
# Reads used across scenarios
# ---------------------------------------------------------------------------

def get_posting(posting_id) -> dict:
    return _ok(api_client.get_procurement_posting(posting_id, READER), "get_posting")


def get_bid(bid_id) -> dict:
    return _ok(api_client.get_bid(bid_id, READER), "get_bid")


def get_contract(contract_id) -> dict:
    return _ok(api_client.get_contract(contract_id, READER), "get_contract")


def get_request(request_id) -> dict:
    return _ok(api_client.get_funding_request(request_id, READER), "get_funding_request")


def get_line(line_id) -> dict:
    return _ok(api_client.get_funding_request_line(line_id, READER), "get_line")


def get_invoice(invoice_id) -> dict:
    return _ok(api_client.get_invoice_submission(invoice_id, READER), "get_invoice")


def get_substitution(substitution_id) -> dict:
    return _ok(api_client.get_service_substitution(substitution_id, READER),
               "get_substitution")


def get_appeal(appeal_id) -> dict:
    return _ok(api_client.get_appeal(appeal_id, READER), "get_appeal")


def get_document(document_id) -> dict:
    return _ok(api_client.get_retained_document(document_id, READER), "get_document")


def get_applicant(applicant_id) -> dict:
    return _ok(api_client.get_applicant(applicant_id, READER), "get_applicant")


def budget_summary(applicant_id, cycle_id) -> dict:
    return _ok(api_client.get_budget_summary(
        applicant_id, READER, params={"funding_cycle_id": cycle_id}), "budget_summary")
