"""Composite setup helpers.

The harness restarts the service before every individual test, so each test
starts from an empty store with the logical clock at its default instant. That
makes the long PRD workflows - activate a profile, vet a subscriber, run a key
ceremony, validate domain control, clear validation, issue, revoke, publish -
repeat verbatim in almost every test, so they are built once here.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from . import test_users as users
from .api_client import CaApiClient
from .api_errors import install_error_status_map
from .assertions import plus_days
from .constants import (
    CHECK_PASSED,
    CLOCK_EPOCH,
    CT_OUTCOME_ACCEPTED,
    DCV_METHOD_DNS_TXT,
    DIMENSION_AUTHORITY,
    DIMENSION_CALLBACK,
    DIMENSION_REGISTRY,
    ALL_LOG_OPERATORS,
    REASON_UNSPECIFIED,
    VALIDATION_TYPE_EV,
    VETTING_LEVEL_EV,
    VETTING_LEVEL_OV,
)
from . import factories as make

DEFAULT_WINDOW_START = CLOCK_EPOCH
DEFAULT_WINDOW_END = "2026-08-01T00:30:00Z"


# ---------------------------------------------------------------------------
# Low level primitives
# ---------------------------------------------------------------------------
def advance_clock(client: CaApiClient, instant: str, headers=None) -> Dict[str, Any]:
    response = client.set_clock(instant, headers or users.POLICY_ADMIN)
    return get_success_data(response)


def create_profile(
    client: CaApiClient, payload: Optional[Dict] = None, activate: bool = True
) -> Dict[str, Any]:
    """Create a certificate profile and, by default, activate it."""
    body = payload if payload is not None else make.profile_payload()
    profile = get_success_data(client.create_profile(body, users.POLICY_ADMIN), 201)
    if activate:
        profile = get_success_data(
            client.activate_profile(profile["id"], users.POLICY_ADMIN)
        )
    return profile


def create_subscriber(
    client: CaApiClient, payload: Optional[Dict] = None
) -> Dict[str, Any]:
    body = payload if payload is not None else make.subscriber_payload()
    return get_success_data(client.create_subscriber(body, users.POLICY_ADMIN), 201)


def create_partition(
    client: CaApiClient, payload: Optional[Dict] = None
) -> Dict[str, Any]:
    body = payload if payload is not None else make.partition_payload()
    return get_success_data(client.create_partition(body, users.POLICY_ADMIN), 201)


def read_profile(client: CaApiClient, profile_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_profile(profile_id, users.POLICY_ADMIN))


def read_subscriber(client: CaApiClient, subscriber_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_subscriber(subscriber_id, users.POLICY_ADMIN))


def read_authorization(client: CaApiClient, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_authorization(authorization_id, users.VALIDATION_OFFICER)
    )


def read_request(client: CaApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_request(request_id, users.VALIDATION_OFFICER))


def read_certificate(client: CaApiClient, certificate_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_certificate(certificate_id, users.ISSUANCE_OPERATOR)
    )


def read_ceremony(client: CaApiClient, ceremony_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_ceremony(ceremony_id, users.ISSUANCE_OPERATOR))


def read_partition(client: CaApiClient, partition_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_partition(partition_id, users.POLICY_ADMIN))


def read_revocation(client: CaApiClient, revocation_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_revocation(revocation_id, users.REVOCATION_OFFICER)
    )


def read_incident(client: CaApiClient, incident_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_incident(incident_id, users.COMPLIANCE_AUDITOR)
    )


def read_audit(client: CaApiClient, audit_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_audit(audit_id, users.COMPLIANCE_AUDITOR))


def profile_version(client: CaApiClient, profile_id: str) -> int:
    return read_profile(client, profile_id)["version"]


# ---------------------------------------------------------------------------
# Organization vetting (PRD 3.3)
# ---------------------------------------------------------------------------
def approve_vetting_file(
    client: CaApiClient,
    subscriber_id: str,
    required_level: str = VETTING_LEVEL_OV,
    checker=None,
    approver=None,
) -> Dict[str, Any]:
    """Open a vetting file, pass every required dimension and approve it."""
    checker = checker or users.VALIDATION_OFFICER
    approver = approver or users.VETTING_APPROVER
    vetting = get_success_data(
        client.open_vetting(
            subscriber_id, make.vetting_payload(required_level), checker
        ),
        201,
    )
    dimensions = [DIMENSION_REGISTRY, DIMENSION_CALLBACK]
    if required_level == VETTING_LEVEL_EV:
        dimensions.append(DIMENSION_AUTHORITY)
    for dimension in dimensions:
        validate_success(
            client.record_check(
                vetting["id"], make.check_payload(dimension, CHECK_PASSED), checker
            )
        )
    return get_success_data(client.approve_vetting(vetting["id"], approver))


# ---------------------------------------------------------------------------
# Key ceremonies (PRD 3.6)
# ---------------------------------------------------------------------------
def schedule_ceremony(
    client: CaApiClient,
    partition_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    attestation_valid_days: int = 60,
    scheduler=None,
) -> Dict[str, Any]:
    return get_success_data(
        client.schedule_ceremony(
            partition_id,
            make.ceremony_payload(window_start, window_end, attestation_valid_days),
            scheduler or users.ISSUANCE_OPERATOR,
        ),
        201,
    )


def witness_twice(client: CaApiClient, ceremony_id: str, first=None, second=None):
    """Two distinct witnesses move a ceremony from SCHEDULED to WITNESSED."""
    validate_success(
        client.witness_ceremony(ceremony_id, first or users.ISSUANCE_OPERATOR)
    )
    return get_success_data(
        client.witness_ceremony(ceremony_id, second or users.ISSUANCE_OPERATOR_2)
    )


def attest_ceremony_at_window_end(
    client: CaApiClient,
    ceremony_id: str,
    window_end: str = DEFAULT_WINDOW_END,
    attester=None,
) -> Dict[str, Any]:
    """Move the clock to the close of the window, then attest."""
    advance_clock(client, window_end)
    return get_success_data(
        client.attest_ceremony(ceremony_id, attester or users.COMPLIANCE_AUDITOR)
    )


def attested_ceremony(
    client: CaApiClient,
    partition_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    attestation_valid_days: int = 60,
    attester=None,
) -> Dict[str, Any]:
    """Schedule, witness twice and attest a ceremony in one call."""
    ceremony = schedule_ceremony(
        client, partition_id, window_start, window_end, attestation_valid_days
    )
    witness_twice(client, ceremony["id"])
    return attest_ceremony_at_window_end(
        client, ceremony["id"], window_end, attester=attester
    )


# ---------------------------------------------------------------------------
# Domain control validation (PRD 3.4)
# ---------------------------------------------------------------------------
def create_authorization(
    client: CaApiClient,
    subscriber_id: str,
    profile_id: str,
    domain_name: str = "d1.example.org",
    method: str = DCV_METHOD_DNS_TXT,
    officer=None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_authorization(
            make.authorization_payload(subscriber_id, profile_id, domain_name, method),
            officer or users.VALIDATION_OFFICER,
        ),
        201,
    )


def validate_authorization(
    client: CaApiClient, authorization: Dict[str, Any], officer=None
) -> Dict[str, Any]:
    """Answer a challenge with the token the service minted for it."""
    return get_success_data(
        client.validate_authorization(
            authorization["id"],
            make.validate_payload(authorization["challenge_token"]),
            officer or users.VALIDATION_OFFICER,
        )
    )


def validated_authorization(
    client: CaApiClient,
    subscriber_id: str,
    profile_id: str,
    domain_name: str = "d1.example.org",
    method: str = DCV_METHOD_DNS_TXT,
    officer=None,
) -> Dict[str, Any]:
    pending = create_authorization(
        client, subscriber_id, profile_id, domain_name, method, officer
    )
    validated = validate_authorization(client, pending, officer)
    validated["challenge_token"] = pending["challenge_token"]
    return validated


# ---------------------------------------------------------------------------
# The recurring backbone
# ---------------------------------------------------------------------------
@dataclass
class Environment:
    """An activated profile, a subscriber, and an attested ceremony to sign on."""

    profile: Dict[str, Any]
    subscriber: Dict[str, Any]
    partition: Dict[str, Any]
    ceremony: Dict[str, Any]
    authorizations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    vetting: Optional[Dict[str, Any]] = None

    @property
    def profile_id(self) -> str:
        return self.profile["id"]

    @property
    def subscriber_id(self) -> str:
        return self.subscriber["id"]

    @property
    def partition_id(self) -> str:
        return self.partition["id"]

    @property
    def ceremony_id(self) -> str:
        return self.ceremony["id"]

    def authorization(self, domain: str) -> Dict[str, Any]:
        return self.authorizations[domain]


def build_environment(
    client: CaApiClient,
    profile_payload: Optional[Dict] = None,
    subscriber_payload: Optional[Dict] = None,
    domains: Sequence[str] = ("d1.example.org",),
    method: str = DCV_METHOD_DNS_TXT,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    attestation_valid_days: int = 60,
    validate_domains: bool = True,
    vetting_level: Optional[str] = None,
) -> Environment:
    """Set up everything an issuance needs, in the order the PRD allows.

    Domain authorizations are created after the ceremony has been attested, so
    they are validated at the close of the ceremony window.
    """
    profile = create_profile(client, profile_payload)
    subscriber = create_subscriber(client, subscriber_payload)
    partition = create_partition(client)
    ceremony = attested_ceremony(
        client, partition["id"], window_start, window_end, attestation_valid_days
    )
    vetting = None
    if vetting_level is not None:
        vetting = approve_vetting_file(client, subscriber["id"], vetting_level)
    authorizations = {}
    for domain in domains:
        if validate_domains:
            authorizations[domain] = validated_authorization(
                client, subscriber["id"], profile["id"], domain, method
            )
        else:
            authorizations[domain] = create_authorization(
                client, subscriber["id"], profile["id"], domain, method
            )
    return Environment(
        profile=profile,
        subscriber=subscriber,
        partition=partition,
        ceremony=ceremony,
        authorizations=authorizations,
        vetting=vetting,
    )


# ---------------------------------------------------------------------------
# Certificate requests (PRD 3.5)
# ---------------------------------------------------------------------------
def create_request(
    client: CaApiClient,
    subscriber_id: str,
    profile_id: str,
    domains: Sequence[str] = ("d1.example.org",),
    requested_validity_days: int = 90,
    csr_key_bits: int = 2048,
    expedited: bool = False,
    officer=None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_request(
            make.certificate_request_payload(
                subscriber_id,
                profile_id,
                list(domains),
                requested_validity_days,
                csr_key_bits,
                expedited,
            ),
            officer or users.VALIDATION_OFFICER,
        ),
        201,
    )


def submitted_request(client: CaApiClient, *args, officer=None, **kwargs) -> Dict[str, Any]:
    officer = officer or users.VALIDATION_OFFICER
    request = create_request(client, *args, officer=officer, **kwargs)
    return get_success_data(client.submit_request(request["id"], officer))


def cleared_request(client: CaApiClient, *args, officer=None, **kwargs) -> Dict[str, Any]:
    """Create, submit and clear validation on one request."""
    officer = officer or users.VALIDATION_OFFICER
    request = submitted_request(client, *args, officer=officer, **kwargs)
    return get_success_data(client.clear_validation(request["id"], officer))


def issue_from_request(
    client: CaApiClient, request_id: str, ceremony_id: str, issuer=None, supersedes=None
) -> Dict[str, Any]:
    return get_success_data(
        client.issue_certificate(
            request_id,
            make.issue_payload(ceremony_id, supersedes),
            issuer or users.ISSUANCE_OPERATOR_9,
        ),
        201,
    )


def issue_certificate(
    client: CaApiClient,
    environment: Environment,
    domains: Sequence[str] = ("d1.example.org",),
    requested_validity_days: int = 90,
    csr_key_bits: int = 2048,
    expedited: bool = False,
    clearer=None,
    issuer=None,
    supersedes=None,
) -> Dict[str, Any]:
    """Run one request all the way from DRAFT to an issued certificate."""
    clearer = clearer or users.VALIDATION_OFFICER
    request = cleared_request(
        client,
        environment.subscriber_id,
        environment.profile_id,
        domains,
        requested_validity_days,
        csr_key_bits,
        expedited,
        officer=clearer,
    )
    return issue_from_request(
        client, request["id"], environment.ceremony_id, issuer, supersedes
    )


def add_scts(
    client: CaApiClient, certificate_id: str, count: int, operator=None
) -> List[Dict[str, Any]]:
    """Accept one submission per distinct log operator until `count` is reached."""
    submissions = []
    for index in range(count):
        submissions.append(
            get_success_data(
                client.submit_ct_log(
                    certificate_id,
                    make.ct_submission_payload(
                        ALL_LOG_OPERATORS[index], CT_OUTCOME_ACCEPTED
                    ),
                    operator or users.ISSUANCE_OPERATOR,
                ),
                201,
            )
        )
    return submissions


def activate_certificate(
    client: CaApiClient, certificate: Dict[str, Any], required_sct_count: int, operator=None
) -> Dict[str, Any]:
    """Log enough SCTs to satisfy the profile, then activate."""
    add_scts(client, certificate["id"], required_sct_count, operator)
    return get_success_data(
        client.activate_certificate(
            certificate["id"], operator or users.ISSUANCE_OPERATOR
        )
    )


# ---------------------------------------------------------------------------
# Revocation (PRD 3.8)
# ---------------------------------------------------------------------------
def raise_revocation(
    client: CaApiClient,
    certificate: Dict[str, Any],
    reason_code: str = REASON_UNSPECIFIED,
    incident_id: Optional[str] = None,
    evidence_ref: Optional[str] = None,
    officer=None,
) -> Dict[str, Any]:
    return get_success_data(
        client.raise_revocation(
            make.revocation_payload(
                certificate["id"],
                reason_code,
                certificate["version"],
                incident_id,
                evidence_ref,
            ),
            officer or users.REVOCATION_OFFICER,
        ),
        201,
    )


def revoke_certificate(
    client: CaApiClient,
    certificate: Dict[str, Any],
    reason_code: str = REASON_UNSPECIFIED,
    incident_id: Optional[str] = None,
    evidence_ref: Optional[str] = None,
    officer=None,
) -> Dict[str, Any]:
    """Raise and then execute a revocation on one certificate."""
    officer = officer or users.REVOCATION_OFFICER
    request = raise_revocation(
        client, certificate, reason_code, incident_id, evidence_ref, officer
    )
    return get_success_data(client.execute_revocation(request["id"], officer))


def publish_crl(
    client: CaApiClient,
    profile_id: str,
    this_update: str,
    next_update: str,
    officer=None,
) -> Dict[str, Any]:
    """Publish a CRL, reading the profile version the OCC guard expects."""
    version = profile_version(client, profile_id)
    return get_success_data(
        client.publish_crl(
            profile_id,
            make.crl_publication_payload(this_update, next_update, version),
            officer or users.REVOCATION_OFFICER,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Compliance (PRD 3.9)
# ---------------------------------------------------------------------------
def open_incident(
    client: CaApiClient, scope_profile_id: str, auditor=None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        client.create_incident(
            make.incident_payload(scope_profile_id, **overrides),
            auditor or users.COMPLIANCE_AUDITOR,
        ),
        201,
    )


def disclosed_incident(
    client: CaApiClient, scope_profile_id: str, auditor=None, **overrides
) -> Dict[str, Any]:
    """Open an incident and immediately disclose it to a root program."""
    auditor = auditor or users.COMPLIANCE_AUDITOR
    incident = open_incident(client, scope_profile_id, auditor, **overrides)
    return get_success_data(
        client.disclose_incident(
            incident["id"], make.disclosure_payload(), auditor
        )
    )


def open_audit(client: CaApiClient, auditor=None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_audit(
            make.audit_payload(**overrides), auditor or users.COMPLIANCE_AUDITOR
        ),
        201,
    )


def audit_with_findings(
    client: CaApiClient, severities: Sequence[str], auditor=None, **overrides
) -> Dict[str, Any]:
    auditor = auditor or users.COMPLIANCE_AUDITOR
    audit = open_audit(client, auditor, **overrides)
    for severity in severities:
        validate_success(
            client.record_finding(
                audit["id"], make.finding_payload(severity), auditor
            )
        )
    return get_success_data(client.get_audit(audit["id"], auditor))


def opined_audit(
    client: CaApiClient, severities: Sequence[str], auditor=None, opiner=None, **overrides
) -> Dict[str, Any]:
    auditor = auditor or users.COMPLIANCE_AUDITOR
    audit = audit_with_findings(client, severities, auditor, **overrides)
    return get_success_data(
        client.opine_audit(audit["id"], opiner or auditor)
    )


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _error_status_map():
    """Register the PRD's error-to-status table with the shared validators."""
    return install_error_status_map()


@pytest.fixture
def client() -> CaApiClient:
    return CaApiClient()


@pytest.fixture
def api(client) -> CaApiClient:
    return client


@pytest.fixture
def dv_environment(client) -> Environment:
    """One activated DV profile, one subscriber, one attested ceremony."""
    return build_environment(client)


@pytest.fixture
def ev_environment(client) -> Environment:
    """The EV variant, with an approved EV vetting file on the subscriber."""
    return build_environment(
        client,
        profile_payload=make.ev_profile_payload(),
        vetting_level=VETTING_LEVEL_EV,
    )


__all__ = [name for name in dir() if not name.startswith("_")]
