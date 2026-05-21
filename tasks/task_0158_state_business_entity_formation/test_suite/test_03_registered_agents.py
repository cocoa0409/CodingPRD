"""RegisteredAgent CRUD, P.O. Box prohibition, and resignation.

Covers PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_registered_agent,
    assert_status,
    create_registered_agent,
    create_registered_agent_payload,
    make_registered_agent_headers,
    patch_registered_agent_payload,
    resign_registered_agent,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Create agent — PRD §3.2
# ---------------------------------------------------------------------------
class TestCreateRegisteredAgent:

    def test_create_agent_with_valid_inputs(
        self, api, registered_agent_service_headers,
    ):
        """PRD §3.2: "Creating an agent — done either by a
        RegisteredAgentService or by a StateRegistrar — requires
        agent_name, physical_address, and service_state."

        Claim: a valid agent payload returns 201 with the expected
        fields and status defaulted to ACTIVE.
        """
        payload = create_registered_agent_payload(
            service_state="DE", physical_address="123 Main St",
        )
        resp = api.create_registered_agent(
            payload, registered_agent_service_headers,
        )
        agent = validate_success(resp, expected_status=201)
        assert_registered_agent(agent)
        assert_status(agent, "ACTIVE")
        # PRD §3.2: agents start with their status defaulted to ACTIVE.
        # resignation_effective_at should be null at create.
        assert agent.get("resignation_effective_at") is None


# ---------------------------------------------------------------------------
# P.O. Box prohibition — PRD §3.2
# ---------------------------------------------------------------------------
class TestPOBoxProhibition:

    # PRD §3.2 makes the prohibition formal via the regular expression
    # ^P\.?O\.? Box. The prose mentions "P O Box" but the *formal*
    # regex (the binding rule per PRD §2.11 priority 9) does NOT match
    # "P O Box" — \.?O requires P/O to be contiguous with at most a
    # single dot between. We therefore only parametrize on prefixes the
    # PRD's regex actually catches.
    @pytest.mark.parametrize("addr", [
        "P.O. Box 123",
        "PO Box 456",
        "P.O. Box 12345 Suite 6",
    ])
    def test_po_box_address_rejected(
        self, api, registered_agent_service_headers, addr,
    ):
        """PRD §3.2: "the address must not start with a match of the
        regular expression ^P\\.?O\\.? Box; a violation is rejected with
        ERR_INVALID_AGENT_ADDRESS and HTTP 422."

        Claim: an address matching the P.O. Box prefix pattern →
        ERR_INVALID_AGENT_ADDRESS.
        """
        payload = create_registered_agent_payload(
            service_state="DE", physical_address=addr,
        )
        resp = api.create_registered_agent(
            payload, registered_agent_service_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AGENT_ADDRESS.value)

    def test_po_box_in_patch_rejected(self, api):
        """PRD §3.2: "The same address constraint applies when an
        agent's physical_address is updated via the agent-edit
        endpoint."
        PRD §2.1: "When X-User-Role is RegisteredAgentService, X-User-ID
        is the id of the acting RegisteredAgent row; that identifier is
        the agent the caller may resign or update." → PATCH requires
        ownership-matching headers.

        Claim: PATCH physical_address to a P.O. Box → same error.
        """
        agent = create_registered_agent(
            service_state="DE", physical_address="100 Real Street",
        )
        resp = api.patch_registered_agent(
            agent["id"],
            patch_registered_agent_payload(physical_address="P.O. Box 9"),
            make_registered_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AGENT_ADDRESS.value)


# ---------------------------------------------------------------------------
# OCC on PATCH — PRD §2.5
# ---------------------------------------------------------------------------
class TestRegisteredAgentOCC:

    def test_patch_with_matching_version_increments_version(self, api):
        """PRD §2.5: "When the client supplies a version, the server
        compares it to the persisted version on the row; if they do not
        match, the request is rejected with ERR_VERSION_CONFLICT and
        HTTP 409. ... A successful mutation increments version by one"
        PRD §2.1: RegisteredAgentService's X-User-ID is the id of the
        agent the caller may update; PATCH must come from owner headers.

        Claim: PATCH with the correct version succeeds and bumps version
        by exactly one.
        """
        agent = create_registered_agent(service_state="DE")
        original_version = agent["version"]
        resp = api.patch_registered_agent(
            agent["id"],
            patch_registered_agent_payload(
                agent_name="Renamed Agent", version=original_version,
            ),
            make_registered_agent_headers(agent["id"]),
        )
        updated = validate_success(resp)
        assert updated["agent_name"] == "Renamed Agent"
        assert updated["version"] == original_version + 1, (
            f"Expected version {original_version + 1}, got "
            f"{updated['version']}"
        )

    def test_patch_with_wrong_version_rejected(self, api):
        """PRD §2.5: "if they do not match, the request is rejected with
        ERR_VERSION_CONFLICT and HTTP 409."
        PRD §2.1: RegisteredAgentService's X-User-ID is the id of the
        agent the caller may update; PATCH must come from owner headers.

        Claim: PATCH with mismatched version → ERR_VERSION_CONFLICT.
        """
        agent = create_registered_agent(service_state="DE")
        resp = api.patch_registered_agent(
            agent["id"],
            patch_registered_agent_payload(
                agent_name="Bad", version=agent["version"] + 99,
            ),
            make_registered_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ---------------------------------------------------------------------------
# Resignation — PRD §3.2
# ---------------------------------------------------------------------------
class TestResignation:

    def test_resign_transitions_to_resigned(self, api):
        """PRD §3.2: "A RegisteredAgentService may resign one of its
        agents, which transitions status to RESIGNED and writes the
        current clock instant into resignation_effective_at."

        Claim: resign → RESIGNED + resignation_effective_at set.
        """
        agent = create_registered_agent(service_state="DE")
        resp = api.resign_registered_agent(
            agent["id"], make_registered_agent_headers(agent["id"]),
        )
        resigned = validate_success(resp)
        assert_status(resigned, "RESIGNED")
        assert resigned.get("resignation_effective_at") is not None

    def test_resign_already_resigned_rejected(self, api):
        """PRD §2.11: "(6) the target resource is in a state that
        permits the requested operation (yielding ERR_INVALID_STATE)"
        PRD §3.2: resign transitions ACTIVE → RESIGNED; RESIGNED is
        terminal for the agent lifecycle.

        Claim: resign on an already-RESIGNED agent → ERR_INVALID_STATE.
        """
        agent = create_registered_agent(service_state="DE")
        resign_registered_agent(agent["id"])
        # Second resign — same agent, already RESIGNED.
        resp = api.resign_registered_agent(
            agent["id"], make_registered_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
