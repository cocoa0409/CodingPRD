"""Composite state builders.

Every helper here drives the public API only - there is no direct database
access - so each one is a real end-to-end journey through the documented
workflows.  Tests compose them instead of repeating twelve-call setups.

Ownership-scoped calls always thread the entity-backed identity of the row
that owns them: activation and consent run as the credential's own holder,
reader-app registration and disclosure run as the reader app's own verifier.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories
from .api_client import MdlApiClient
from .test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
    PROOFING_AGENT,
    make_holder_headers,
    make_verifier_operator_headers,
)

STRONG_DOCUMENT_AND_BIOMETRIC = [
    {
        "evidence_type": "DOCUMENT_SCAN",
        "quality": "STRONG",
        "captured_at": "2026-07-20T09:00:00Z",
        "source_reference": "doc-1",
    },
    {
        "evidence_type": "BIOMETRIC_MATCH",
        "quality": "STRONG",
        "captured_at": "2026-07-20T09:05:00Z",
        "source_reference": "bio-1",
    },
]


# ==========================================================================
# Tier 1 - single rows
# ==========================================================================
def create_profile(api: MdlApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create the interoperability profile that governs issuance."""
    response = api.create_interop_profile(
        factories.interop_profile_payload(**overrides), ADMIN
    )
    return validate_success(response, 201)


def read_profile(api: MdlApiClient, profile_id: str) -> Dict[str, Any]:
    return validate_success(api.get_interop_profile(profile_id, ADMIN), 200)


def profile_version(api: MdlApiClient, profile_id: str) -> int:
    return read_profile(api, profile_id)["version"]


def create_holder(api: MdlApiClient, **overrides: Any) -> Dict[str, Any]:
    """Enrol a person who already holds a valid physical driver license."""
    response = api.create_holder(factories.holder_payload(**overrides), ADMIN)
    return validate_success(response, 201)


def register_device(
    api: MdlApiClient, holder_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register a handset in state REGISTERED."""
    response = api.create_device(
        factories.device_payload(holder_id, **overrides),
        make_holder_headers(holder_id),
    )
    return validate_success(response, 201)


def attest_device(
    api: MdlApiClient,
    device_id: str,
    attestation_result: str = "PASS",
    secure_element_grade: str = "HARDWARE_STRONGBOX",
) -> Dict[str, Any]:
    """Run hardware attestation on a registered handset."""
    response = api.attest_device(
        device_id,
        factories.attestation_payload(attestation_result, secure_element_grade),
        ADMIN,
    )
    return validate_success(response, 200)


def device_version(api: MdlApiClient, device_id: str) -> int:
    return validate_success(api.get_device(device_id, ADMIN), 200)["version"]


def create_attested_device(
    api: MdlApiClient,
    holder_id: str,
    secure_element_grade: str = "HARDWARE_STRONGBOX",
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a handset and carry it through a passing attestation."""
    device = register_device(api, holder_id, **overrides)
    return attest_device(api, device["id"], "PASS", secure_element_grade)


# ==========================================================================
# Tier 2 - identity proofing progression
# ==========================================================================
def open_proofing_session(
    api: MdlApiClient,
    holder_id: str,
    requested_assurance_level: str = "IAL2",
    agent_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a proofing session in state COLLECTING."""
    response = api.create_proofing_session(
        factories.proofing_session_payload(
            holder_id, requested_assurance_level=requested_assurance_level
        ),
        agent_headers or PROOFING_AGENT,
    )
    return validate_success(response, 201)


def append_evidence(
    api: MdlApiClient,
    session_id: str,
    items: List[Dict[str, Any]],
    agent_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Append a batch of evidence items to a COLLECTING session."""
    headers = agent_headers or PROOFING_AGENT
    created = []
    for item in items:
        response = api.add_proofing_evidence(
            session_id, factories.evidence_payload(**item), headers
        )
        created.append(validate_success(response, 201))
    return created


def submit_session(
    api: MdlApiClient,
    session_id: str,
    agent_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Submit a COLLECTING session for adjudication."""
    response = api.submit_proofing_session(session_id, agent_headers or PROOFING_AGENT)
    return validate_success(response, 200)


def adjudicate_session(
    api: MdlApiClient,
    session_id: str,
    decision: str = "VERIFY",
    return_reason: Optional[str] = None,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adjudicate a SUBMITTED session; the adjudicator must not be the agent."""
    payload: Dict[str, Any] = {"decision": decision}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    response = api.adjudicate_proofing_session(
        session_id, payload, adjudicator_headers or ADJUDICATOR
    )
    return validate_success(response, 200)


def create_verified_session(
    api: MdlApiClient,
    holder_id: str,
    evidence: Optional[List[Dict[str, Any]]] = None,
    requested_assurance_level: str = "IAL2",
    agent_headers: Optional[Dict[str, str]] = None,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Take a proofing session all the way to VERIFIED."""
    session = open_proofing_session(
        api, holder_id, requested_assurance_level, agent_headers
    )
    append_evidence(
        api,
        session["id"],
        evidence if evidence is not None else STRONG_DOCUMENT_AND_BIOMETRIC,
        agent_headers,
    )
    submit_session(api, session["id"], agent_headers)
    return adjudicate_session(
        api, session["id"], "VERIFY", None, adjudicator_headers
    )


# ==========================================================================
# Tier 3 - credential provisioning and activation
# ==========================================================================
def provision_credential(
    api: MdlApiClient,
    holder_id: str,
    device_id: str,
    proofing_session_id: str,
    expected_device_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Provision a credential in PENDING_PROVISION, echoing the device version."""
    if expected_device_version is None:
        expected_device_version = device_version(api, device_id)
    response = api.create_credential(
        factories.credential_payload(
            holder_id, device_id, proofing_session_id, expected_device_version, **overrides
        ),
        ADJUDICATOR,
    )
    return validate_success(response, 201)


def activate_credential(
    api: MdlApiClient,
    credential_id: str,
    holder_id: str,
    device_unlock_proof: str = "BIOMETRIC",
) -> Dict[str, Any]:
    """Activate a provisioned credential from the holder's own handset."""
    response = api.activate_credential(
        credential_id,
        {"device_unlock_proof": device_unlock_proof},
        make_holder_headers(holder_id),
    )
    return validate_success(response, 200)


def create_active_credential(
    api: MdlApiClient,
    profile: Optional[Dict[str, Any]] = None,
    holder: Optional[Dict[str, Any]] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    protection_method: str = "BIOMETRIC",
    valid_from: str = "2026-08-01T00:00:00Z",
    valid_until: str = "2031-07-01T00:00:00Z",
) -> Dict[str, Any]:
    """Whole issuance journey: profile, holder, handset, proofing, ACTIVE mDL.

    Returns a bundle of every row the journey created so callers can keep
    driving the same graph.
    """
    profile = profile or create_profile(api)
    holder = holder or create_holder(api)
    device = create_attested_device(
        api, holder["id"], protection_method=protection_method
    )
    session = create_verified_session(api, holder["id"], evidence)
    credential = provision_credential(
        api,
        holder["id"],
        device["id"],
        session["id"],
        valid_from=valid_from,
        valid_until=valid_until,
    )
    credential = activate_credential(
        api, credential["id"], holder["id"], protection_method
    )
    return {
        "profile": profile,
        "holder": holder,
        "device": device,
        "session": session,
        "credential": credential,
    }


# ==========================================================================
# Tier 3 - verifier onboarding and trust distribution
# ==========================================================================
def create_verifier(api: MdlApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a relying party; it starts in trust_status APPLIED."""
    response = api.create_verifier(factories.verifier_payload(**overrides), ADMIN)
    return validate_success(response, 201)


def decide_trust(api: MdlApiClient, verifier_id: str, decision: str) -> Dict[str, Any]:
    response = api.decide_verifier_trust(verifier_id, {"decision": decision}, ADMIN)
    return validate_success(response, 200)


def create_approved_verifier(api: MdlApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a relying party and approve it onto the trust list."""
    verifier = create_verifier(api, **overrides)
    return decide_trust(api, verifier["id"], "APPROVE")


def register_reader_app(
    api: MdlApiClient, verifier_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register a reader application as its own verifier operator."""
    response = api.create_reader_app(
        factories.reader_app_payload(verifier_id, **overrides),
        make_verifier_operator_headers(verifier_id),
    )
    return validate_success(response, 201)


def decide_listing(
    api: MdlApiClient, reader_app_id: str, decision: str
) -> Dict[str, Any]:
    response = api.decide_reader_listing(reader_app_id, {"decision": decision}, ADMIN)
    return validate_success(response, 200)


def create_listed_reader_app(
    api: MdlApiClient, verifier_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register a reader application and list it on the trust list."""
    reader_app = register_reader_app(api, verifier_id, **overrides)
    return decide_listing(api, reader_app["id"], "LIST")


def publish_trust_list(
    api: MdlApiClient,
    profile_id: str,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_until: str = "2026-12-01T00:00:00Z",
) -> Dict[str, Any]:
    """Publish a trust-list snapshot, echoing the profile's current version."""
    response = api.create_trust_list_snapshot(
        factories.trust_list_snapshot_payload(
            profile_id,
            profile_version(api, profile_id),
            effective_from,
            effective_until,
        ),
        ADMIN,
    )
    return validate_success(response, 201)


# ==========================================================================
# Tier 4 - the whole presentation graph
# ==========================================================================
def create_presentation_ready_world(
    api: MdlApiClient,
    verifier_overrides: Optional[Dict[str, Any]] = None,
    reader_app_overrides: Optional[Dict[str, Any]] = None,
    credential_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An ACTIVE credential, an approved verifier, a listed reader app and a
    published trust list - everything a presentation request needs."""
    bundle = create_active_credential(api, **(credential_overrides or {}))
    verifier = create_approved_verifier(api, **(verifier_overrides or {}))
    reader_app = create_listed_reader_app(
        api, verifier["id"], **(reader_app_overrides or {})
    )
    snapshot = publish_trust_list(api, bundle["profile"]["id"])
    bundle.update(
        {"verifier": verifier, "reader_app": reader_app, "snapshot": snapshot}
    )
    return bundle


def open_presentation_session(
    api: MdlApiClient,
    world: Dict[str, Any],
    expected_status: int = 201,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a presentation request as the reader app's own verifier operator."""
    response = api.create_presentation_session(
        factories.presentation_session_payload(
            world["credential"]["id"], world["reader_app"]["id"], **overrides
        ),
        make_verifier_operator_headers(world["verifier"]["id"]),
    )
    return validate_success(response, expected_status)


def grant_consent(
    api: MdlApiClient,
    session_id: str,
    holder_id: str,
    unlock_method: str = "BIOMETRIC",
) -> Dict[str, Any]:
    response = api.consent_presentation(
        session_id,
        factories.consent_payload("APPROVE", unlock_method),
        make_holder_headers(holder_id),
    )
    return validate_success(response, 200)


def disclose(
    api: MdlApiClient, session_id: str, verifier_id: str
) -> Dict[str, Any]:
    response = api.disclose_presentation(
        session_id, make_verifier_operator_headers(verifier_id)
    )
    return validate_success(response, 200)


def complete_presentation(
    api: MdlApiClient, world: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """Open, consent and disclose a presentation in one call."""
    session = open_presentation_session(api, world, **overrides)
    grant_consent(api, session["id"], world["holder"]["id"])
    return disclose(api, session["id"], world["verifier"]["id"])


# ==========================================================================
# Tier 5 - clock and read-through utilities
# ==========================================================================
def set_clock(api: MdlApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock; only this endpoint moves it."""
    return validate_success(api.set_clock(to_iso8601, ADMIN), 200)


def rows(response) -> List[Dict[str, Any]]:
    data = get_success_data(response)
    assert isinstance(data, list)
    return data


def first_delivery_of(api: MdlApiClient, order_id: str) -> Dict[str, Any]:
    """The single delivery a singleton update order opened."""
    delivery_rows = rows(api.list_order_deliveries(order_id, ADMIN))
    assert delivery_rows, "expected the order to have opened at least one delivery"
    return delivery_rows[0]


def open_address_change(
    api: MdlApiClient, holder_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.change_holder_address(
        holder_id, factories.address_change_payload(**overrides), ADMIN
    )
    return validate_success(response, 201)


# ==========================================================================
# pytest fixtures
# ==========================================================================
@pytest.fixture
def profile(api: MdlApiClient) -> Dict[str, Any]:
    """The governing interoperability profile, all defaults taken."""
    return create_profile(api)


@pytest.fixture
def holder(api: MdlApiClient, profile: Dict[str, Any]) -> Dict[str, Any]:
    """One enrolled holder under the governing profile."""
    return create_holder(api)


@pytest.fixture
def attested_device(api: MdlApiClient, holder: Dict[str, Any]) -> Dict[str, Any]:
    """One handset that has passed hardware attestation."""
    return create_attested_device(api, holder["id"])


@pytest.fixture
def verified_session(api: MdlApiClient, holder: Dict[str, Any]) -> Dict[str, Any]:
    """One proofing session verified at IAL2."""
    return create_verified_session(api, holder["id"])


@pytest.fixture
def active_credential_world(api: MdlApiClient) -> Dict[str, Any]:
    """Profile, holder, attested handset, verified proofing and an ACTIVE mDL."""
    return create_active_credential(api)


@pytest.fixture
def presentation_world(api: MdlApiClient) -> Dict[str, Any]:
    """The full presentation graph, ready for a reader request."""
    return create_presentation_ready_world(api)


@pytest.fixture
def approved_verifier(api: MdlApiClient) -> Dict[str, Any]:
    """One relying party approved onto the trust list."""
    return create_approved_verifier(api)


@pytest.fixture
def auditor_headers() -> Dict[str, str]:
    return PRIVACY_AUDITOR
