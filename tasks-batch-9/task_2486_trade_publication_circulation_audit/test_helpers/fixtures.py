"""Composable fixtures and state builders.

The server is restarted before every test, so every fixture here builds the
state it needs from an empty database and from the default logical clock of
2026-08-01T00:00:00Z (PRD §2.5).
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .test_users import (
    AUDITOR_HEADERS,
    AUDITOR_SECONDARY,
    EXECUTIVE_HEADERS,
    MANAGER_HEADERS,
    MANAGER_SECONDARY,
    SPECIALIST_HEADERS,
    make_advertiser_contact_headers,
    make_circulation_auditor_headers,
    make_circulation_manager_headers,
)
from .types import (
    SnapshotDecision,
    StatementBasis,
    SubscriptionClass,
)

# A clock earlier than the reporting period used by the statement fixtures, so
# that a qualification window opened here starts strictly before `period_end`.
QUALIFY_CLOCK = "2026-03-01T00:00:00Z"
QUALIFY_SIGNED_AT = "2026-02-15T00:00:00Z"
QUALIFY_CAPTURED_AT = "2026-02-01T00:00:00Z"

# The reporting period the statement fixtures use: closed before the default clock.
PERIOD_START = "2026-04-01T00:00:00Z"
PERIOD_END = "2026-07-01T00:00:00Z"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def move_clock(to_iso8601, headers=None):
    response = api_client.set_clock(to_iso8601, headers or MANAGER_HEADERS)
    return get_success_data(response)


@pytest.fixture
def client():
    return api_client


@pytest.fixture
def clock():
    """Move the logical clock and hand back a mover for further moves."""

    def _move(to_iso8601, headers=None):
        return move_clock(to_iso8601, headers)

    return _move


# --------------------------------------------------------------------------
# Tier 1 — publications and qualification policy
# --------------------------------------------------------------------------
def register_publication(headers=None, **overrides):
    response = api_client.create_publication(
        f.publication_payload(**overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def add_rule(publication_id, payload, headers=None):
    response = api_client.create_qualification_rule(
        publication_id, payload, headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def add_complete_rule_set(publication_id, headers=None):
    return [
        add_rule(publication_id, payload, headers)
        for payload in f.complete_rule_set_payloads()
    ]


def read_publication(publication_id, headers=None):
    response = api_client.get_publication(publication_id, headers or MANAGER_HEADERS)
    return get_success_data(response)


@pytest.fixture
def publication():
    """A registered publication with no qualification rules yet."""
    return register_publication()


@pytest.fixture
def publication_with_rules():
    """A publication holding one rule per dimension: 45 + 30 + 25 base points."""
    pub = register_publication()
    add_complete_rule_set(pub["id"])
    return read_publication(pub["id"])


# --------------------------------------------------------------------------
# Tier 2 — recipients and evidence
# --------------------------------------------------------------------------
def add_subscriber(publication_id, headers=None, **overrides):
    response = api_client.create_subscriber(
        f.subscriber_payload(publication_id, **overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def read_subscriber(subscriber_id, headers=None):
    response = api_client.get_subscriber(subscriber_id, headers or MANAGER_HEADERS)
    return get_success_data(response)


def attach_source_document(subscriber_id, headers=None, **overrides):
    response = api_client.create_source_document(
        subscriber_id, f.source_document_payload(**overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


@pytest.fixture
def subscriber(publication_with_rules):
    """A freshly enrolled recipient of a fully configured publication."""
    return add_subscriber(publication_with_rules["id"])


@pytest.fixture
def subscriber_factory(publication_with_rules):
    def _make(**overrides):
        return add_subscriber(publication_with_rules["id"], **overrides)

    return _make


# --------------------------------------------------------------------------
# Tier 3 — qualification requests and verified recipients
# --------------------------------------------------------------------------
def open_request(subscriber_id, source_document_id, version, headers=None, **overrides):
    response = api_client.create_qualification_request(
        f.qualification_request_payload(
            subscriber_id, source_document_id, version, **overrides
        ),
        headers or MANAGER_HEADERS,
    )
    return get_success_data(response)


def review_request(request_id, headers=None, **overrides):
    response = api_client.review_qualification_request(
        request_id, f.review_payload(**overrides), headers or SPECIALIST_HEADERS
    )
    return get_success_data(response)


def verify_request(request_id, headers=None, **overrides):
    response = api_client.verify_qualification_request(
        request_id, f.verify_payload(**overrides), headers or SPECIALIST_HEADERS
    )
    return get_success_data(response)


def submit_and_review(subscriber_id, source_document_id, version, **overrides):
    request = open_request(subscriber_id, source_document_id, version, **overrides)
    return review_request(request["id"])


def qualify_subscriber(
    publication_id,
    signed_at=QUALIFY_SIGNED_AT,
    captured_at=QUALIFY_CAPTURED_AT,
    request_overrides=None,
    **subscriber_overrides,
):
    """Enrol a recipient, attach evidence, and carry a request through to VERIFIED."""
    subscriber = add_subscriber(publication_id, **subscriber_overrides)
    document = attach_source_document(subscriber["id"], captured_at=captured_at)
    overrides = dict(request_overrides or {})
    overrides.setdefault("signed_at", signed_at)
    request = open_request(
        subscriber["id"], document["id"], subscriber["version"], **overrides
    )
    review_request(request["id"])
    verify_request(request["id"])
    return {
        "subscriber": read_subscriber(subscriber["id"]),
        "source_document": document,
        "request": request,
    }


@pytest.fixture
def request_under_review(publication_with_rules):
    """A qualification request taken into review, with its recipient and evidence."""
    subscriber = add_subscriber(publication_with_rules["id"])
    document = attach_source_document(subscriber["id"])
    request = open_request(subscriber["id"], document["id"], subscriber["version"])
    reviewed = review_request(request["id"])
    return {
        "publication": publication_with_rules,
        "subscriber": subscriber,
        "source_document": document,
        "request": reviewed,
    }


@pytest.fixture
def qualified_subscriber(publication_with_rules):
    """A verified, deliverable recipient qualified at the default clock."""
    return qualify_subscriber(
        publication_with_rules["id"],
        signed_at="2026-07-15T00:00:00Z",
        captured_at="2026-07-01T00:00:00Z",
    )


# --------------------------------------------------------------------------
# Tier 4 — statements
# --------------------------------------------------------------------------
def qualified_population(publication_id, specs):
    """Qualify a set of recipients at an earlier clock, then return to the default.

    `specs` is a list of keyword dicts passed to the recipient factory, so a
    caller can shape the class mix and copy counts the breakdown will read.
    """
    move_clock(QUALIFY_CLOCK)
    members = [qualify_subscriber(publication_id, **spec) for spec in specs]
    move_clock(DEFAULT_CLOCK)
    return members


def open_statement(publication_id, headers=None, **overrides):
    publication = read_publication(publication_id)
    payload = f.statement_payload(
        publication_id, publication["version"], **overrides
    )
    response = api_client.create_statement(payload, headers or MANAGER_HEADERS)
    return get_success_data(response)


def read_statement(statement_id, headers=None):
    response = api_client.get_statement(statement_id, headers or MANAGER_HEADERS)
    return get_success_data(response)


def recompute_statement(statement_id, headers=None, **overrides):
    response = api_client.recompute_statement(
        statement_id, f.recompute_payload(**overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def certify_statement(statement_id, headers=None, **overrides):
    response = api_client.certify_statement(
        statement_id, f.certify_payload(**overrides), headers or EXECUTIVE_HEADERS
    )
    return get_success_data(response)


def file_statement(publication_id, headers=None, **overrides):
    """Open a DRAFT statement as mgr-01 and certify it as the executive."""
    statement = open_statement(publication_id, headers=headers, **overrides)
    return certify_statement(statement["id"])


@pytest.fixture
def draft_statement(publication_with_rules):
    """A DRAFT statement over a closed period with one qualified paid recipient."""
    publication_id = publication_with_rules["id"]
    members = qualified_population(
        publication_id,
        [
            {
                "subscription_class": SubscriptionClass.PAID.value,
                "paid_amount_cents": 12000,
                "copies": 100,
            }
        ],
    )
    statement = open_statement(publication_id)
    return {
        "publication": read_publication(publication_id),
        "members": members,
        "statement": statement,
    }


@pytest.fixture
def filed_statement(draft_statement):
    """A statement carried DRAFT -> FILED, certified by an actor who did not prepare it."""
    filed = certify_statement(draft_statement["statement"]["id"])
    return {
        "publication": read_publication(draft_statement["publication"]["id"]),
        "members": draft_statement["members"],
        "statement": filed,
    }


# --------------------------------------------------------------------------
# Tier 5 — engagements, findings, contracts, make-goods, snapshots
# --------------------------------------------------------------------------
def open_engagement(statement_id, headers=None, **overrides):
    response = api_client.create_audit_engagement(
        f.engagement_payload(statement_id, **overrides), headers or AUDITOR_HEADERS
    )
    return get_success_data(response)


def record_sample(engagement_id, subscriber_id, headers=None, **overrides):
    response = api_client.record_sample_verification(
        engagement_id,
        f.sample_verification_payload(subscriber_id, **overrides),
        headers or AUDITOR_HEADERS,
    )
    return get_success_data(response)


def raise_finding(engagement_id, headers=None, **overrides):
    response = api_client.create_audit_finding(
        f.finding_payload(engagement_id, **overrides), headers or AUDITOR_HEADERS
    )
    return get_success_data(response)


def respond_to_finding(finding_id, headers=None, **overrides):
    response = api_client.respond_to_finding(
        finding_id, f.finding_response_payload(**overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def accept_finding(finding_id, headers=None, **overrides):
    response = api_client.accept_finding_resolution(
        finding_id,
        f.accept_resolution_payload(**overrides),
        headers or make_circulation_auditor_headers(AUDITOR_SECONDARY),
    )
    return get_success_data(response)


def issue_report(engagement_id, headers=None, **overrides):
    response = api_client.issue_report(
        engagement_id, f.issue_report_payload(**overrides), headers or AUDITOR_HEADERS
    )
    return get_success_data(response)


@pytest.fixture
def engagement_in_reconciliation(filed_statement):
    """A one-record engagement that auto-advanced SCHEDULED -> RECONCILIATION."""
    statement = filed_statement["statement"]
    engagement = open_engagement(statement["id"], sample_size=1)
    subscriber_id = filed_statement["members"][0]["subscriber"]["id"]
    engagement = record_sample(
        engagement["id"],
        subscriber_id,
        verified_copies=statement["declared_total_copies"],
    )
    return {
        "publication": read_publication(filed_statement["publication"]["id"]),
        "members": filed_statement["members"],
        "statement": read_statement(statement["id"]),
        "engagement": engagement,
    }


def register_contract(publication_id, headers=None, **overrides):
    response = api_client.create_advertiser_contract(
        f.advertiser_contract_payload(publication_id, **overrides),
        headers or MANAGER_HEADERS,
    )
    return get_success_data(response)


def read_contract(contract_id, headers=None):
    response = api_client.get_advertiser_contract(
        contract_id, headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def settle_guarantees(statement_id, headers=None, **overrides):
    response = api_client.settle_guarantees(
        statement_id, f.settle_guarantees_payload(**overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def offer_make_good(make_good_id, headers=None, **overrides):
    response = api_client.offer_make_good(
        make_good_id, f.offer_payload(**overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def accept_make_good(make_good_id, contract_id, **overrides):
    response = api_client.accept_make_good(
        make_good_id,
        f.accept_makegood_payload(**overrides),
        make_advertiser_contact_headers(contract_id),
    )
    return get_success_data(response)


def waive_make_good(make_good_id, headers=None, **overrides):
    response = api_client.waive_make_good(
        make_good_id, f.waive_payload(**overrides), headers or EXECUTIVE_HEADERS
    )
    return get_success_data(response)


def record_snapshot(publication_id, headers=None, **overrides):
    response = api_client.create_digital_snapshot(
        publication_id, f.digital_snapshot_payload(**overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


def adjudicate_snapshot(
    snapshot_id, decision=SnapshotDecision.VALIDATE.value, headers=None
):
    response = api_client.validate_digital_snapshot(
        snapshot_id, f.snapshot_decision_payload(decision), headers or AUDITOR_HEADERS
    )
    return get_success_data(response)


def run_hygiene_sweep(publication_id, headers=None, **overrides):
    response = api_client.create_hygiene_run(
        f.hygiene_run_payload(publication_id, **overrides), headers or MANAGER_HEADERS
    )
    return get_success_data(response)


@pytest.fixture
def critical_finding_frozen(engagement_in_reconciliation):
    """A publication frozen by a single open CRITICAL finding."""
    engagement = engagement_in_reconciliation["engagement"]
    finding = raise_finding(
        engagement["id"],
        severity="CRITICAL",
        affected_copies=10,
        subscriber_id=engagement_in_reconciliation["members"][0]["subscriber"]["id"],
    )
    return {
        "publication": read_publication(
            engagement_in_reconciliation["publication"]["id"]
        ),
        "members": engagement_in_reconciliation["members"],
        "statement": read_statement(
            engagement_in_reconciliation["statement"]["id"]
        ),
        "engagement": engagement,
        "finding": finding,
    }


@pytest.fixture
def condemned_statement(filed_statement):
    """A statement driven to RESTATEMENT_REQUIRED by a material audit variance."""
    statement = filed_statement["statement"]
    engagement = open_engagement(statement["id"], sample_size=1)
    record_sample(
        engagement["id"],
        filed_statement["members"][0]["subscriber"]["id"],
        evidence_ok=False,
        verified_copies=0,
    )
    issue_report(engagement["id"])
    return {
        "publication": read_publication(filed_statement["publication"]["id"]),
        "members": filed_statement["members"],
        "statement": read_statement(statement["id"]),
        "engagement": engagement,
    }
