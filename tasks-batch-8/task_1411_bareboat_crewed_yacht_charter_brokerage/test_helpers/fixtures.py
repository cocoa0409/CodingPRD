"""Composite setup helpers for multi-step test prerequisites.

The interesting claims in this PRD (quote computation, escrow settlement,
cancellation cascades, permit roll-ups) all require 5-15 API calls of setup:
operator + brokers + qualified client + listed yacht + request + offer +
accept + insurance + signatures + tranches. These fixtures encapsulate the
plumbing so tests focus on assertions.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before every test) and threads entity-backed
identities through make_*_headers so ownership checks see the real entity id.

All setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure deep in a test.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_accept_payload,
    create_availability_block_payload,
    create_broker_payload,
    create_charter_request_payload,
    create_client_payload,
    create_counter_payload,
    create_expense_payload,
    create_fund_payload,
    create_insurance_certificate_payload,
    create_itinerary_leg_payload,
    create_operator_payload,
    create_port_permit_payload,
    create_resume_payload,
    create_yacht_payload,
)
from .test_users import (
    TEST_USERS,
    make_central_agent_headers,
    make_client_headers,
    make_operator_headers,
    make_platform_admin_headers,
    make_retail_broker_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_failed(step: str, res):
    raise AssertionError(
        f"Setup failed at step '{step}': HTTP {res.status_code}: {res.text}")


def _ok(res, step: str):
    data = get_success_data(res)
    if res.status_code >= 400:
        _setup_failed(step, res)
    return data


# ─── Tier 0: marketplace actors ──────────────────────────────────────

def create_operator(name: str = "Op One", home_port: str = "Athens") -> dict:
    res = api_client.create_operator(
        create_operator_payload(name=name, home_port=home_port), ADMIN)
    return _ok(res, "create_operator")


def create_central_agent(display_name: str = "CA One",
                         license_no: str = "LIC-CA-1",
                         broker_type: str = "CENTRAL_AGENT") -> dict:
    res = api_client.create_broker(
        create_broker_payload(display_name=display_name,
                              broker_type=broker_type,
                              license_no=license_no), ADMIN)
    return _ok(res, "create_central_agent")


def create_retail_broker(display_name: str = "RB One",
                         license_no: str = "LIC-RB-1") -> dict:
    return create_central_agent(display_name=display_name,
                                license_no=license_no,
                                broker_type="RETAIL_BROKER")


def create_client(full_name: str = "Cy Client", email: str = "cy@example.com") -> dict:
    res = api_client.create_client(
        create_client_payload(full_name=full_name, email=email), ADMIN)
    return _ok(res, "create_client")


def submit_resume(client_id: str, resume_class: str = "OFFSHORE",
                  skippered_hours: int = 300) -> dict:
    res = api_client.submit_resume(
        client_id,
        create_resume_payload(resume_class=resume_class,
                              skippered_hours=skippered_hours),
        make_client_headers(client_id))
    return _ok(res, "submit_resume")


def review_resume(client_id: str, outcome: str) -> dict:
    res = api_client.review_resume(client_id, {"outcome": outcome}, ADMIN)
    return _ok(res, "review_resume")


def create_qualified_client(resume_class: str = "OFFSHORE",
                            skippered_hours: int = 300,
                            full_name: str = "Cy Client",
                            email: str = "cy@example.com") -> dict:
    """Client taken through UNVERIFIED -> PENDING_REVIEW -> QUALIFIED."""
    client = create_client(full_name=full_name, email=email)
    submit_resume(client["id"], resume_class, skippered_hours)
    return review_resume(client["id"], "QUALIFIED")


# ─── Tier 1: yachts ──────────────────────────────────────────────────

def create_yacht(operator_id: str, central_agent_id: str, **overrides) -> dict:
    """Create a yacht (starts DRAFT) owned by `operator_id`."""
    res = api_client.create_yacht(
        create_yacht_payload(central_agent_id, **overrides),
        make_operator_headers(operator_id))
    return _ok(res, "create_yacht")


def create_listed_yacht(operator_id: str, central_agent_id: str, **overrides) -> dict:
    """Create a yacht and list it. Returns the LISTED yacht."""
    yacht = create_yacht(operator_id, central_agent_id, **overrides)
    res = api_client.list_yacht(yacht["id"], make_operator_headers(operator_id))
    return _ok(res, "list_yacht")


def create_manual_block(yacht_id: str, operator_id: str, expected_yacht_version: int,
                        **overrides) -> dict:
    res = api_client.create_availability_block(
        yacht_id,
        create_availability_block_payload(expected_yacht_version, **overrides),
        make_operator_headers(operator_id))
    return _ok(res, "create_manual_block")


# ─── Tier 2: charter request lifecycle ───────────────────────────────

def create_request(client_id: str, yacht_id: str,
                   start_date: str = "2026-10-01", end_date: str = "2026-10-11",
                   guests_count: int = 4, as_role: str = "Client",
                   caller_id: str = None, **extra) -> dict:
    """Create a DRAFT charter request.

    as_role == "Client": caller is the client; retail_broker_id may be passed
        via extra.
    as_role == "RetailBroker": caller is the retail broker (retail_broker_id
        is set to the caller by the server); caller_id is the broker id.
    """
    payload = create_charter_request_payload(
        client_id, yacht_id, start_date=start_date, end_date=end_date,
        guests_count=guests_count, **extra)
    if as_role == "RetailBroker":
        headers = make_retail_broker_headers(caller_id)
    else:
        headers = make_client_headers(caller_id or client_id)
    res = api_client.create_charter_request(payload, headers)
    return _ok(res, "create_request")


def submit_request(request_id: str, caller_id: str, as_role: str = "Client") -> dict:
    headers = (make_retail_broker_headers(caller_id) if as_role == "RetailBroker"
               else make_client_headers(caller_id))
    res = api_client.submit_charter_request(request_id, headers)
    return _ok(res, "submit_request")


def make_offer(request_id: str, central_agent_id: str, **terms) -> dict:
    """Issue an offer from the yacht's listing central agent.

    retail_pct_bps is pinned to TEST_DEFAULTS["RETAIL_PCT_BPS"] unless
    overridden: the PRD leaves no default for it, so scenarios that later
    assert exact commission shares must fix the split explicitly.
    """
    terms.setdefault("retail_pct_bps", TEST_DEFAULTS["RETAIL_PCT_BPS"])
    res = api_client.offer_charter_request(
        request_id, terms, make_central_agent_headers(central_agent_id))
    return _ok(res, "make_offer")


def counter_request(request_id: str, caller_id: str, expected_version: int,
                    as_role: str = "Client", **extra) -> dict:
    headers = (make_retail_broker_headers(caller_id) if as_role == "RetailBroker"
               else make_client_headers(caller_id))
    res = api_client.counter_charter_request(
        request_id,
        create_counter_payload(expected_version, **extra),
        headers)
    return _ok(res, "counter_request")


def accept_request(request_id: str, caller_id: str, expected_version: int,
                   as_role: str = "Client") -> dict:
    """Accept the current offer. Returns the created CharterAgreement (201)."""
    headers = (make_retail_broker_headers(caller_id) if as_role == "RetailBroker"
               else make_client_headers(caller_id))
    res = api_client.accept_charter_request(
        request_id, create_accept_payload(expected_version), headers)
    data = _ok(res, "accept_request")
    if res.status_code != 201:
        _setup_failed("accept_request (expected 201)", res)
    return data


def decline_request(request_id: str, caller_id: str, as_role: str = "Client") -> dict:
    headers = (make_retail_broker_headers(caller_id) if as_role == "RetailBroker"
               else make_client_headers(caller_id))
    res = api_client.decline_charter_request(request_id, headers)
    return _ok(res, "decline_request")


# ─── Tier 3: escrow / agreement helpers ──────────────────────────────

def get_agreement_escrow(agreement_id: str, headers=None) -> dict:
    """Read the agreement's escrow sub-resource (array of length 0-1)."""
    res = api_client.get_agreement_escrow(agreement_id, headers or ADMIN)
    data = _ok(res, "get_agreement_escrow")
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one escrow account for agreement {agreement_id}, "
        f"got {data}")
    return data[0]


def list_movements(escrow_id: str, headers=None, **params) -> list:
    """List ALL movements of an escrow in posted order.

    Settlement scenarios post 11+ movements (4 funding + 7-8 cascade), past
    the PRD default page size of 10 — pin limit=100 (the PRD maximum) unless
    the caller overrides it.
    """
    params.setdefault("limit", 100)
    res = api_client.list_escrow_movements(escrow_id, headers or ADMIN,
                                           params=params)
    return _ok(res, "list_movements")


def file_verified_insurance(agreement_id: str, central_agent_id: str,
                            coverage_amount_cents: int = None,
                            valid_from: str = None, valid_until: str = None,
                            policy_no: str = "POL-1") -> dict:
    """Central agent files a certificate; PlatformAdmin verifies it.

    Defaults are read off the agreement: coverage == charter_fee_cents and a
    window generously containing the charter window on closed bounds.
    """
    agreement = _ok(api_client.get_charter_agreement(agreement_id, ADMIN),
                    "get_charter_agreement")
    payload = create_insurance_certificate_payload(
        agreement["charter_fee_cents"],
        agreement["start_date"],
        agreement["end_date"],
        policy_no=policy_no)
    if coverage_amount_cents is not None:
        payload["coverage_amount_cents"] = coverage_amount_cents
    if valid_from is not None:
        payload["valid_from"] = valid_from
    if valid_until is not None:
        payload["valid_until"] = valid_until
    res = api_client.create_insurance_certificate(
        agreement_id, payload, make_central_agent_headers(central_agent_id))
    cert = _ok(res, "create_insurance_certificate")
    res = api_client.verify_insurance_certificate(
        cert["id"], {"outcome": "VERIFIED"}, ADMIN)
    return _ok(res, "verify_insurance_certificate")


def sign_as_client(agreement_id: str, client_id: str) -> dict:
    res = api_client.sign_charter_agreement(
        agreement_id, make_client_headers(client_id))
    return _ok(res, "sign_as_client")


def sign_as_central_agent(agreement_id: str, central_agent_id: str) -> dict:
    res = api_client.sign_charter_agreement(
        agreement_id, make_central_agent_headers(central_agent_id))
    return _ok(res, "sign_as_central_agent")


def sign_both(agreement_id: str, client_id: str, central_agent_id: str) -> dict:
    """Client signs, then the central agent: the second signature flips SIGNED."""
    sign_as_client(agreement_id, client_id)
    return sign_as_central_agent(agreement_id, central_agent_id)


def fund_tranche(agreement_id: str, tranche: str, amount_cents: int,
                 funder_id: str, as_role: str = "Client") -> dict:
    """Fund one tranche; returns the updated EscrowAccount."""
    headers = (make_retail_broker_headers(funder_id) if as_role == "RetailBroker"
               else make_client_headers(funder_id))
    res = api_client.fund_charter_agreement(
        agreement_id, create_fund_payload(tranche, amount_cents), headers)
    return _ok(res, f"fund_tranche({tranche})")


def fund_all(agreement_id: str, funder_id: str, as_role: str = "Client") -> dict:
    """Fund SIGNING then FINAL at the exact computed dues. Returns escrow."""
    agreement = _ok(api_client.get_charter_agreement(agreement_id, ADMIN),
                    "get_charter_agreement")
    fund_tranche(agreement_id, "SIGNING", agreement["signing_due_cents"],
                 funder_id, as_role)
    return fund_tranche(agreement_id, "FINAL", agreement["final_due_cents"],
                        funder_id, as_role)


def set_clock(to_iso8601: str) -> dict:
    res = api_client.set_clock({"to_iso8601": to_iso8601},
                               make_platform_admin_headers())
    return _ok(res, "set_clock")


# ─── Tier 4: composite deal builders ─────────────────────────────────

def setup_marketplace(yacht_overrides: dict = None,
                      qualify: bool = True,
                      resume_class: str = "OFFSHORE",
                      skippered_hours: int = 300,
                      yacht_preset: dict = None) -> SimpleNamespace:
    """Operator + central agent + (optionally QUALIFIED) client + DRAFT yacht.

    Returns a namespace with .operator, .central_agent, .client, .yacht and
    convenience header callables bound to the real entity ids.
    """
    operator = create_operator()
    central_agent = create_central_agent()
    if qualify:
        client = create_qualified_client(resume_class=resume_class,
                                         skippered_hours=skippered_hours)
    else:
        client = create_client()
    overrides = dict(yacht_preset or {})
    overrides.update(yacht_overrides or {})
    yacht = create_yacht(operator["id"], central_agent["id"], **overrides)
    return SimpleNamespace(
        operator=operator, central_agent=central_agent, client=client,
        yacht=yacht,
        op_headers=make_operator_headers(operator["id"]),
        ca_headers=make_central_agent_headers(central_agent["id"]),
        cl_headers=make_client_headers(client["id"]),
    )


def setup_listed_marketplace(**kwargs) -> SimpleNamespace:
    """setup_marketplace with the yacht LISTED."""
    ctx = setup_marketplace(**kwargs)
    res = api_client.list_yacht(ctx.yacht["id"], ctx.op_headers)
    ctx.yacht = _ok(res, "list_yacht")
    return ctx


def setup_submitted_request(start_date: str = "2026-10-01",
                            end_date: str = "2026-10-11",
                            guests_count: int = 4,
                            **marketplace_kwargs) -> SimpleNamespace:
    """Listed yacht + QUALIFIED client + a SUBMITTED request."""
    ctx = setup_listed_marketplace(**marketplace_kwargs)
    ctx.request = create_request(ctx.client["id"], ctx.yacht["id"],
                                 start_date=start_date, end_date=end_date,
                                 guests_count=guests_count)
    ctx.request = submit_request(ctx.request["id"], ctx.client["id"])
    return ctx


def setup_offered_request(offer_overrides: dict = None,
                          **kwargs) -> SimpleNamespace:
    """Submitted request + one offer. The returned .request is OFFERED and its
    version is the one a subsequent counter/accept must carry."""
    ctx = setup_submitted_request(**kwargs)
    ctx.request = make_offer(ctx.request["id"], ctx.central_agent["id"],
                             **(offer_overrides or {}))
    return ctx


def setup_accepted_agreement(offer_overrides: dict = None, **kwargs) -> SimpleNamespace:
    """Offer accepted: CharterAgreement (PENDING_SIGNATURES / UNFUNDED),
    OPEN escrow, and the CHARTER block all exist. Adds .agreement and
    .escrow to the context."""
    ctx = setup_offered_request(offer_overrides=offer_overrides, **kwargs)
    ctx.agreement = accept_request(ctx.request["id"], ctx.client["id"],
                                   ctx.request["version"])
    ctx.escrow = get_agreement_escrow(ctx.agreement["id"])
    return ctx


def setup_signed_agreement(**kwargs) -> SimpleNamespace:
    """Accepted agreement + VERIFIED insurance + both signatures (SIGNED)."""
    ctx = setup_accepted_agreement(**kwargs)
    ctx.insurance = file_verified_insurance(ctx.agreement["id"],
                                            ctx.central_agent["id"])
    ctx.agreement = sign_both(ctx.agreement["id"], ctx.client["id"],
                              ctx.central_agent["id"])
    return ctx


def setup_fully_funded_agreement(**kwargs) -> SimpleNamespace:
    """SIGNED agreement with both tranches funded (FULLY_FUNDED)."""
    ctx = setup_signed_agreement(**kwargs)
    ctx.escrow = fund_all(ctx.agreement["id"], ctx.client["id"])
    ctx.agreement = _ok(
        api_client.get_charter_agreement(ctx.agreement["id"], ADMIN),
        "get_charter_agreement")
    return ctx


def setup_in_prep_agreement(**kwargs) -> SimpleNamespace:
    """FULLY_FUNDED agreement moved to IN_PREP (no legs -> permit gate passes)."""
    ctx = setup_fully_funded_agreement(**kwargs)
    res = api_client.start_prep(ctx.agreement["id"], ctx.op_headers)
    ctx.agreement = _ok(res, "start_prep")
    return ctx


def setup_underway_agreement(charter_start: str = "2026-11-02", **kwargs) -> SimpleNamespace:
    """IN_PREP agreement embarked to UNDERWAY (clock advanced to start_date)."""
    ctx = setup_in_prep_agreement(**kwargs)
    set_clock(f"{charter_start}T00:00:00Z")
    res = api_client.embark(ctx.agreement["id"], ctx.op_headers)
    ctx.agreement = _ok(res, "embark")
    return ctx


# ─── Tier 5: itinerary / expense helpers ─────────────────────────────

def add_itinerary_leg(agreement_id: str, central_agent_id: str,
                      **overrides) -> dict:
    res = api_client.create_itinerary_leg(
        agreement_id, create_itinerary_leg_payload(**overrides),
        make_central_agent_headers(central_agent_id))
    return _ok(res, "create_itinerary_leg")


def add_port_permit(leg_id: str, central_agent_id: str, **overrides) -> dict:
    res = api_client.create_port_permit(
        leg_id, create_port_permit_payload(**overrides),
        make_central_agent_headers(central_agent_id))
    return _ok(res, "create_port_permit")


def decide_permit(permit_id: str, outcome: str) -> dict:
    res = api_client.decide_port_permit(permit_id, {"outcome": outcome}, ADMIN)
    return _ok(res, "decide_permit")


def add_expense(agreement_id: str, operator_id: str, **overrides) -> dict:
    res = api_client.create_expense(
        agreement_id, create_expense_payload(**overrides),
        make_operator_headers(operator_id))
    return _ok(res, "create_expense")


def review_expense(expense_id: str, outcome: str, reviewer_id: str,
                   as_role: str = "Client") -> dict:
    headers = (make_retail_broker_headers(reviewer_id) if as_role == "RetailBroker"
               else make_client_headers(reviewer_id))
    res = api_client.review_expense(expense_id, {"outcome": outcome}, headers)
    return _ok(res, "review_expense")
