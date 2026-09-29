"""Pytest fixtures for the Fair Trade Certification API suite.

The harness restarts the server and empties the database before every single
test, so every fixture here builds its world from scratch through the endpoints
the PRD declares. Nothing is shared across tests and nothing is seeded directly
into storage.

The fixtures are layered:

* tier 1 - the HTTP client;
* tier 2 - the logical clock;
* tier 3 - single entities in a named state;
* tier 4 - a mapped certified chain, a funded committee, a started audit,
  a licensed brand;
* tier 5 - whole scenarios: a settled trade, an approved proposal, a suspended
  holder, a chain positioned for escalation, a counterparty report pair.
"""

from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_ISO
from .test_users import (
    AUDITOR,
    CHAIR,
    MEMBER_1,
    MEMBER_2,
    MEMBER_3,
    OFFICER,
    make_brand_licensee_headers,
    make_producer_representative_headers,
)

# ---------------------------------------------------------------------------
# Tier 1 - the client
# ---------------------------------------------------------------------------


@pytest.fixture()
def api() -> ApiClient:
    """A fresh client against the service under test."""
    return ApiClient()


# ---------------------------------------------------------------------------
# Tier 2 - the logical clock
# ---------------------------------------------------------------------------


@pytest.fixture()
def clock(api: ApiClient) -> str:
    """Pin the logical clock at its documented opening instant and return it."""
    f.set_clock(api, DEFAULT_CLOCK_ISO)
    return DEFAULT_CLOCK_ISO


@pytest.fixture()
def advance_clock(api: ApiClient):
    """Move the clock to an explicit instant mid-test."""

    def _advance(to_iso8601: str) -> Dict[str, Any]:
        return f.set_clock(api, to_iso8601)

    return _advance


# ---------------------------------------------------------------------------
# Tier 3 - single entities
# ---------------------------------------------------------------------------


@pytest.fixture()
def pending_producer(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A freshly registered PRODUCER_ORG still sitting at PENDING, with its fund."""
    holder = f.register_holder(api)
    return {
        "holder": holder,
        "holder_id": holder["id"],
        "holder_headers": make_producer_representative_headers(holder["id"]),
    }


@pytest.fixture()
def pending_brand(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A freshly registered BRAND still sitting at PENDING, which gets no fund."""
    holder = f.register_holder(
        api, legal_name="Nordic Roasters", holder_type="BRAND", country_code="SE"
    )
    return {
        "holder": holder,
        "holder_id": holder["id"],
        "holder_headers": make_brand_licensee_headers(holder["id"]),
    }


@pytest.fixture()
def certified_producer(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A CERTIFIED producer with one ACTIVE node and no declared harvest."""
    return f.build_certified_producer(api)


@pytest.fixture()
def harvested_producer(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A CERTIFIED producer whose node holds 50000 kg of declared certified input."""
    return f.build_certified_producer(api, harvest_kg=50000)


# ---------------------------------------------------------------------------
# Tier 4 - a mapped certified chain and its neighbours
# ---------------------------------------------------------------------------


@pytest.fixture()
def physical_chain(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A CERTIFIED producer and brand joined by a PHYSICAL link, 50000 kg declared."""
    return f.build_certified_chain(api)


@pytest.fixture()
def mass_balance_chain(api: ApiClient, clock: str) -> Dict[str, Any]:
    """The same shape as ``physical_chain`` but with a MASS_BALANCE seller node."""
    return f.build_certified_chain(api, seller_mode="MASS_BALANCE")


@pytest.fixture()
def unharvested_chain(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A mapped PHYSICAL chain whose seller node has no certified input at all."""
    return f.build_certified_chain(api, harvest_kg=None)


@pytest.fixture()
def funded_committee(api: ApiClient, clock: str) -> Dict[str, Any]:
    """An ACTIVE committee over a fund holding 2400000 cents from one settled trade."""
    return f.build_funded_committee(api)


@pytest.fixture()
def forming_committee(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A FORMING committee over an empty fund on a mapped chain."""
    chain = f.build_certified_chain(api)
    committee = f.constitute_committee(api, chain["producer_id"])
    chain["committee_id"] = committee["id"]
    return chain


@pytest.fixture()
def started_audit(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A CERTIFIED producer with one IN_PROGRESS audit over 2026-08-01..2026-08-08."""
    producer = f.build_certified_producer(api)
    audit = f.build_started_audit(api, producer["holder_id"])
    producer["audit_id"] = audit["id"]
    producer["audit"] = audit
    return producer


@pytest.fixture()
def licensed_brand(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A CERTIFIED brand holding an ACTIVE licence for 100000 kg, fee unpaid."""
    chain = f.build_certified_chain(api)
    holder = f.issue_license(api, chain["brand_id"], 100000)
    chain["license"] = holder
    chain["license_fee_cents"] = int(holder["license_fee_cents"])
    return chain


@pytest.fixture()
def settled_license_brand(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A CERTIFIED brand whose 100000 kg licence fee has been paid in full."""
    chain = f.build_certified_chain(api)
    holder = f.build_settled_license(api, chain["brand_id"], 100000)
    chain["license"] = holder
    chain["license_fee_cents"] = int(holder["license_fee_cents"])
    return chain


# ---------------------------------------------------------------------------
# Tier 5 - whole scenarios
# ---------------------------------------------------------------------------


@pytest.fixture()
def settled_trade(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A 10000 kg coffee trade recorded, VERIFIED and SETTLED on a PHYSICAL chain."""
    chain = f.build_certified_chain(api)
    committee = f.constitute_committee(api, chain["producer_id"])
    trade = f.record_settled_trade(api, chain, 10000)
    chain["committee_id"] = committee["id"]
    chain["trade_id"] = trade["id"]
    chain["trade"] = trade
    return chain


@pytest.fixture()
def verified_trade(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A 10000 kg coffee trade recorded and VERIFIED but not yet settled."""
    chain = f.build_certified_chain(api)
    trade = f.record_trade(api, chain, 10000)
    f.verify_trade(api, trade["id"])
    chain["trade_id"] = trade["id"]
    return chain


@pytest.fixture()
def approved_proposal(api: ApiClient, clock: str) -> Dict[str, Any]:
    """An APPROVED 500000 cent proposal on a committee funded with 2400000 cents.

    The round is closed by the chair with three APPROVE ballots out of five
    elected members, giving a turnout of 60.00 and an approval of 100.00.
    """
    chain = f.build_funded_committee(api)
    proposal = f.draft_proposal(api, chain, 500000)
    validate_success(api.open_vote(proposal["id"], CHAIR), 200)
    f.cast_ballots(api, proposal["id"], ["APPROVE", "APPROVE", "APPROVE"])
    closed = validate_success(api.close_vote(proposal["id"], CHAIR), 200)
    chain["proposal_id"] = proposal["id"]
    chain["proposal"] = closed
    chain["fund_version"] = f.read_fund(api, chain["producer_id"])["version"]
    return chain


@pytest.fixture()
def draft_proposal_world(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A DRAFT 500000 cent proposal on an ACTIVE committee, no round opened yet."""
    chain = f.build_funded_committee(api)
    proposal = f.draft_proposal(api, chain, 500000)
    chain["proposal_id"] = proposal["id"]
    chain["proposal"] = proposal
    return chain


@pytest.fixture()
def under_vote_proposal(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A 500000 cent proposal sitting at UNDER_VOTE in round 1."""
    chain = f.build_funded_committee(api)
    proposal = f.draft_proposal(api, chain, 500000)
    opened = validate_success(api.open_vote(proposal["id"], CHAIR), 200)
    chain["proposal_id"] = proposal["id"]
    chain["proposal"] = opened
    return chain


@pytest.fixture()
def suspended_producer(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A producer suspended by the officer, so its node is SUSPENDED too."""
    chain = f.build_certified_chain(api)
    validate_success(
        api.suspend_holder(chain["producer_id"], f.reason_payload("MANUAL"), OFFICER), 200
    )
    return chain


@pytest.fixture()
def major_finding(api: ApiClient, clock: str) -> Dict[str, Any]:
    """One MAJOR finding raised against a perfect-scoring producer's started audit."""
    producer = f.build_certified_producer(api)
    audit = f.build_started_audit(api, producer["holder_id"])
    finding = f.raise_finding(api, audit["id"], "MAJOR")
    producer["audit_id"] = audit["id"]
    producer["finding_id"] = finding["id"]
    producer["finding"] = finding
    return producer


@pytest.fixture()
def critical_finding_chain(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A mapped chain whose producer carries one CRITICAL finding due 2026-08-11."""
    chain = f.build_certified_chain(api)
    audit = f.build_started_audit(api, chain["producer_id"])
    finding = f.raise_finding(api, audit["id"], "CRITICAL", "1.1.1", "Forced labour indicator")
    chain["audit_id"] = audit["id"]
    chain["finding_id"] = finding["id"]
    chain["finding"] = finding
    return chain


@pytest.fixture()
def counterparty_report(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A SUBMITTED volume report over 2026-08-01..2026-09-01 against the brand."""
    chain = f.build_certified_chain(api)
    report = f.file_volume_report(
        api, chain["producer_id"], chain["brand_id"], "2026-08-01", "2026-09-01", 12000
    )
    chain["report_id"] = report["id"]
    chain["report"] = report
    return chain


@pytest.fixture()
def mark_request_world(api: ApiClient, clock: str) -> Dict[str, Any]:
    """A SUBMITTED mark usage request against a brand whose licence fee is unpaid."""
    chain = f.build_certified_chain(api)
    holder = f.issue_license(api, chain["brand_id"], 100000)
    request = f.file_mark_usage_request(api, chain["brand_id"])
    chain["license_fee_cents"] = int(holder["license_fee_cents"])
    chain["request_id"] = request["id"]
    chain["request"] = request
    return chain


@pytest.fixture()
def officer_headers() -> Dict[str, str]:
    return OFFICER


@pytest.fixture()
def auditor_headers() -> Dict[str, str]:
    return AUDITOR


@pytest.fixture()
def chair_headers() -> Dict[str, str]:
    return CHAIR


@pytest.fixture()
def member_headers() -> Dict[str, Dict[str, str]]:
    return {"member-1": MEMBER_1, "member-2": MEMBER_2, "member-3": MEMBER_3}
