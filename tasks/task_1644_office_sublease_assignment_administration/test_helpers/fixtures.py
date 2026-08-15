"""Composite setup helpers for the transfer-consent lifecycle.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading (PRD §2.1, §2.9): ownership-gated calls always thread the
acting Party's id through the make_*_headers builders — the landlord of record
decides and signs as LANDLORD, the tenant of record responds/reminds/terminates,
and the transfer's counterparty signs as COUNTERPARTY. The two broker
identities are opaque strings: "broker-1" originates, "broker-2" attests
(segregation of duties, PRD §3.4).
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK, TEST_DEFAULTS as D
from .factories import (
    attest_payload,
    create_building_payload,
    create_demised_area_payload,
    create_lease_payload,
    create_party_payload,
    create_settlement_payload,
    create_transfer_request_payload,
    decide_payload,
    document_payload,
    respond_payload,
    sign_payload,
)
from .test_users import (
    TEST_USERS,
    make_assignee_headers,
    make_landlord_headers,
    make_subtenant_headers,
    make_tenant_headers,
)

MGR = TEST_USERS["asset_manager_headers"]
B1 = TEST_USERS["broker_1_headers"]
B2 = TEST_USERS["broker_2_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, MGR))


# ---------------------------------------------------------------------------
# Portfolio onboarding (Tier 2: entity hierarchy)
# ---------------------------------------------------------------------------

def create_party(party_kind: str, legal_name: str, credit_rating_bps: int) -> dict:
    return get_success_data(api_client.create_party(
        create_party_payload(legal_name=legal_name, party_kind=party_kind,
                             credit_rating_bps=credit_rating_bps),
        MGR,
    ))


def create_building(**overrides) -> dict:
    return get_success_data(api_client.create_building(
        create_building_payload(**overrides), MGR,
    ))


def create_lease(building_id: str, tenant_party_id: str, landlord_party_id: str,
                 **overrides) -> dict:
    payload = create_lease_payload(
        building_id=building_id, tenant_party_id=tenant_party_id,
        landlord_party_id=landlord_party_id, **overrides,
    )
    return get_success_data(api_client.create_lease(payload, MGR))


def standard_portfolio(clock: str = CLOCK["SETUP"],
                       lease_overrides: Optional[Dict] = None,
                       counterparty_kind: str = "SUBTENANT") -> dict:
    """Clock set + landlord/tenant/counterparty parties + building + lease.

    Returns a context dict: pl, pt, ps (the counterparty), bld, lease.
    """
    set_clock(clock)
    pl = create_party("LANDLORD", "Landlord One LLC", D["PARTY_CREDIT_LANDLORD"])
    pt = create_party("TENANT", "Tenant Alpha Inc", D["PARTY_CREDIT_TENANT"])
    if counterparty_kind == "ASSIGNEE":
        ps = create_party("ASSIGNEE", "Assignee One Corp", D["PARTY_CREDIT_COUNTERPARTY"])
    else:
        ps = create_party("SUBTENANT", "SubOne Corp", D["PARTY_CREDIT_COUNTERPARTY"])
    bld = create_building()
    lease = create_lease(bld["id"], pt["id"], pl["id"], **(lease_overrides or {}))
    return {"pl": pl, "pt": pt, "ps": ps, "bld": bld, "lease": lease,
            "counterparty_kind": counterparty_kind}


# ---------------------------------------------------------------------------
# Transfers and measurements (Tier 1: state progression)
# ---------------------------------------------------------------------------

def get_lease(lease_id: str) -> dict:
    return get_success_data(api_client.get_lease(lease_id, B1))


def get_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_transfer_request(transfer_id, B1))


def create_draft_transfer(ctx: dict, broker_headers=B1, **payload_overrides) -> dict:
    """Create a DRAFT transfer against the context lease (OCC on lease version).

    Caller-supplied payload overrides (e.g., a different counterparty for the
    gate-reopens flow) win over the context defaults.
    """
    lease = get_lease(ctx["lease"]["id"])
    merged = {
        "counterparty_id": ctx["ps"]["id"],
        "expected_lease_version": lease["version"],
    }
    merged.update(payload_overrides)
    payload = create_transfer_request_payload(**merged)
    transfer = get_success_data(
        api_client.create_transfer_request(lease["id"], payload, broker_headers)
    )
    ctx["transfer"] = transfer
    ctx["lease"] = get_lease(lease["id"])
    return transfer


def create_measurement(transfer_id: str, broker_headers=B1, **overrides) -> dict:
    return get_success_data(api_client.create_demised_area(
        transfer_id, create_demised_area_payload(**overrides), broker_headers,
    ))


def certify_measurement(area_id: str, broker_headers=B1) -> dict:
    return get_success_data(api_client.certify_demised_area(area_id, broker_headers))


def add_certified_measurement(transfer_id: str, broker_headers=B1, **overrides) -> dict:
    area = create_measurement(transfer_id, broker_headers, **overrides)
    return certify_measurement(area["id"], broker_headers)


def submit_transfer(transfer_id: str, broker_headers=B1) -> dict:
    return get_success_data(api_client.submit_transfer_request(transfer_id, broker_headers))


def withdraw_transfer(transfer_id: str, broker_headers=B1) -> dict:
    return get_success_data(api_client.withdraw_transfer_request(transfer_id, broker_headers))


# ---------------------------------------------------------------------------
# Reviews minted at submission (reverse-reachability lookups)
# ---------------------------------------------------------------------------

def get_consent_review_of(transfer_id: str) -> dict:
    data, _meta = validate_paginated(api_client.get_transfer_consent_review(transfer_id, B1))
    assert len(data) == 1, f"expected exactly one consent review for {transfer_id}"
    return data[0]


def get_credit_review_of(transfer_id: str) -> dict:
    data, _meta = validate_paginated(api_client.get_transfer_credit_review(transfer_id, B1))
    assert len(data) == 1, f"expected exactly one credit review for {transfer_id}"
    return data[0]


def get_recognition_of(transfer_id: str) -> dict:
    data, _meta = validate_paginated(
        api_client.get_transfer_recognition_agreement(transfer_id, B1)
    )
    assert len(data) == 1, f"expected exactly one recognition agreement for {transfer_id}"
    return data[0]


def get_review_fresh(review_id: str) -> dict:
    return get_success_data(api_client.get_consent_review(review_id, B1))


# ---------------------------------------------------------------------------
# Credit attestation and consent decisions
# ---------------------------------------------------------------------------

def attest_credit(review_id: str, rating_bps: int = None, broker_headers=B2) -> dict:
    return get_success_data(api_client.attest_credit_review(
        review_id, attest_payload(rating_bps), broker_headers,
    ))


def decide_consent(review_id: str, landlord_party_id: str, decision: str = "GRANTED",
                   **extra) -> dict:
    """Decide a review as the landlord of record (version re-read for OCC)."""
    current = get_review_fresh(review_id)
    return get_success_data(api_client.decide_consent_review(
        review_id,
        decide_payload(decision, current["version"], **extra),
        make_landlord_headers(landlord_party_id),
    ))


def respond_condition(condition_id: str, tenant_party_id: str,
                      response: str = "ACCEPTED") -> dict:
    return get_success_data(api_client.respond_consent_condition(
        condition_id, respond_payload(response), make_tenant_headers(tenant_party_id),
    ))


def list_conditions(review_id: str) -> List[dict]:
    data, _meta = validate_paginated(api_client.list_consent_conditions(review_id, B1))
    return data


# ---------------------------------------------------------------------------
# Documentation, recognition, effectiveness (Tier 3: full lifecycle)
# ---------------------------------------------------------------------------

def document_transfer(transfer_id: str, broker_headers=B1, **overrides) -> dict:
    """Document a granted transfer; returns the 201 documentation receipt."""
    return get_success_data(api_client.document_transfer_request(
        transfer_id, document_payload(**overrides), broker_headers,
    ))


def sign_recognition(agreement_id: str, signatory: str, party_id: str,
                     counterparty_kind: str = "SUBTENANT") -> dict:
    if signatory == "LANDLORD":
        headers = make_landlord_headers(party_id)
    elif counterparty_kind == "ASSIGNEE":
        headers = make_assignee_headers(party_id)
    else:
        headers = make_subtenant_headers(party_id)
    return get_success_data(api_client.sign_recognition_agreement(
        agreement_id, sign_payload(signatory), headers,
    ))


# ---------------------------------------------------------------------------
# Composite lifecycle fixtures (used across many tests)
# ---------------------------------------------------------------------------

def build_submitted_transfer(clock: str = CLOCK["MONDAY_SUBMIT"],
                             lease_overrides: Optional[Dict] = None,
                             counterparty_kind: str = "SUBTENANT",
                             transfer_overrides: Optional[Dict] = None) -> dict:
    """Portfolio + DRAFT transfer + certified measurement + SUBMITTED.

    Context gains: transfer, consent_review (PENDING), credit_review (PENDING).
    """
    ctx = standard_portfolio(clock=clock, lease_overrides=lease_overrides,
                             counterparty_kind=counterparty_kind)
    create_draft_transfer(ctx, **(transfer_overrides or {}))
    add_certified_measurement(ctx["transfer"]["id"])
    ctx["transfer"] = submit_transfer(ctx["transfer"]["id"])
    ctx["consent_review"] = get_consent_review_of(ctx["transfer"]["id"])
    ctx["credit_review"] = get_credit_review_of(ctx["transfer"]["id"])
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    return ctx


def build_consent_pending_transfer(clock: str = CLOCK["MONDAY_SUBMIT"],
                                   lease_overrides: Optional[Dict] = None,
                                   counterparty_kind: str = "SUBTENANT",
                                   rating_bps: int = None,
                                   transfer_overrides: Optional[Dict] = None) -> dict:
    """Submitted transfer + credit attested by broker-2 -> CONSENT_PENDING."""
    ctx = build_submitted_transfer(clock=clock, lease_overrides=lease_overrides,
                                   counterparty_kind=counterparty_kind,
                                   transfer_overrides=transfer_overrides)
    ctx["credit_review"] = attest_credit(ctx["credit_review"]["id"], rating_bps)
    ctx["transfer"] = get_transfer(ctx["transfer"]["id"])
    return ctx


def build_granted_transfer(clock: str = CLOCK["MONDAY_SUBMIT"],
                           lease_overrides: Optional[Dict] = None,
                           counterparty_kind: str = "SUBTENANT",
                           attest: bool = True,
                           decide_overrides: Optional[Dict] = None,
                           transfer_overrides: Optional[Dict] = None) -> dict:
    """Transfer express-GRANTED by the landlord of record.

    attest=True drives the transfer through CONSENT_PENDING first; with
    attest=False the landlord decides directly from SUBMITTED (both are
    PRD-sanctioned decide states).
    """
    if attest:
        ctx = build_consent_pending_transfer(
            clock=clock, lease_overrides=lease_overrides,
            counterparty_kind=counterparty_kind,
            transfer_overrides=transfer_overrides,
        )
    else:
        ctx = build_submitted_transfer(
            clock=clock, lease_overrides=lease_overrides,
            counterparty_kind=counterparty_kind,
            transfer_overrides=transfer_overrides,
        )
    ctx["consent_review"] = decide_consent(
        ctx["consent_review"]["id"], ctx["pl"]["id"], "GRANTED",
        **(decide_overrides or {}),
    )
    ctx["transfer"] = get_transfer(ctx["transfer"]["id"])
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    return ctx


def build_documented_transfer(clock: str = CLOCK["MONDAY_SUBMIT"],
                              lease_overrides: Optional[Dict] = None,
                              counterparty_kind: str = "SUBTENANT",
                              attest: bool = True,
                              decide_overrides: Optional[Dict] = None,
                              document_overrides: Optional[Dict] = None,
                              transfer_overrides: Optional[Dict] = None) -> dict:
    """Granted transfer + documentation -> DOCUMENTED with receipt ids."""
    ctx = build_granted_transfer(
        clock=clock, lease_overrides=lease_overrides,
        counterparty_kind=counterparty_kind, attest=attest,
        decide_overrides=decide_overrides, transfer_overrides=transfer_overrides,
    )
    receipt = document_transfer(ctx["transfer"]["id"], **(document_overrides or {}))
    ctx["receipt"] = receipt
    ctx["sa_id"] = receipt.get("sublease_agreement_id")
    ctx["ra_id"] = receipt["recognition_agreement_id"]
    ctx["recognition"] = get_recognition_of(ctx["transfer"]["id"])
    ctx["transfer"] = get_transfer(ctx["transfer"]["id"])
    return ctx


def build_effective_transfer(clock: str = CLOCK["MONDAY_SUBMIT"],
                             lease_overrides: Optional[Dict] = None,
                             counterparty_kind: str = "SUBTENANT",
                             sign_order: str = "landlord_first",
                             **kwargs) -> dict:
    """Documented transfer + both recognition signatures -> EFFECTIVE."""
    ctx = build_documented_transfer(
        clock=clock, lease_overrides=lease_overrides,
        counterparty_kind=counterparty_kind, **kwargs,
    )
    if sign_order == "counterparty_first":
        ctx["recognition"] = sign_recognition(
            ctx["ra_id"], "COUNTERPARTY", ctx["ps"]["id"], counterparty_kind,
        )
        ctx["recognition"] = sign_recognition(
            ctx["ra_id"], "LANDLORD", ctx["pl"]["id"], counterparty_kind,
        )
    else:
        ctx["recognition"] = sign_recognition(
            ctx["ra_id"], "LANDLORD", ctx["pl"]["id"], counterparty_kind,
        )
        ctx["recognition"] = sign_recognition(
            ctx["ra_id"], "COUNTERPARTY", ctx["ps"]["id"], counterparty_kind,
        )
    ctx["transfer"] = get_transfer(ctx["transfer"]["id"])
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Conditional-grant fixtures (fork-join)
# ---------------------------------------------------------------------------

def build_conditional_grant(conditions: Optional[List[dict]] = None,
                            clock: str = CLOCK["MONDAY_SUBMIT"],
                            lease_overrides: Optional[Dict] = None,
                            counterparty_kind: str = "SUBTENANT") -> dict:
    """CONSENT_PENDING transfer whose landlord decided GRANTED_WITH_CONDITIONS.

    Context gains: conditions (list of PENDING ConsentCondition rows).
    """
    if conditions is None:
        conditions = [
            {"condition_kind": "RESTORATION_REQUIRED",
             "detail": "Restore demising walls"},
            {"condition_kind": "ADDITIONAL_SECURITY",
             "detail": "Extra 2 months security"},
        ]
    ctx = build_consent_pending_transfer(clock=clock, lease_overrides=lease_overrides,
                                         counterparty_kind=counterparty_kind)
    ctx["consent_review"] = decide_consent(
        ctx["consent_review"]["id"], ctx["pl"]["id"],
        "GRANTED_WITH_CONDITIONS", conditions=conditions,
    )
    ctx["conditions"] = list_conditions(ctx["consent_review"]["id"])
    ctx["transfer"] = get_transfer(ctx["transfer"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Settlements (Tier 4/5: accrual and finalization)
# ---------------------------------------------------------------------------

def create_settlement(ctx: dict, broker_headers=B1, **overrides) -> dict:
    payload = create_settlement_payload(
        lease_id=ctx["lease"]["id"],
        transfer_request_id=ctx["transfer"]["id"],
        **overrides,
    )
    return get_success_data(api_client.create_settlement(payload, broker_headers))


def get_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, B1))
