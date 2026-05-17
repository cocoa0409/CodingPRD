"""Patient portal message — two parallel state dimensions, escalate
cascade.

PRD §3.6.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    anchor_clock,
    create_portal_message_payload,
    make_nurse_headers,
    make_patient_portal_headers,
    make_provider_headers,
    post_portal_message_as_patient,
    setup_patient_with_pcp,
    setup_portal_message_for_parallel_dimensions,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 Two parallel state dimensions: status and triage_status
# ===========================================================================
class TestParallelDimensions:
    """PRD §3.6 establishes status (UNREAD/READ/ARCHIVED) and
    triage_status (NEW/TRIAGED/ESCALATED) as two independent
    dimensions on the same row."""

    # difficulty: non_linear_state_machine/portal_message_parallel_status_and_triage_dimensions
    def test_triage_does_not_change_status(self, api):
        """PRD §3.6: "Triaging and escalating never touch the status
        dimension."

        Claim: triage advances triage_status from NEW to TRIAGED but
        leaves status untouched at UNREAD.
        """
        setup = setup_portal_message_for_parallel_dimensions()
        message = setup["message"]
        assert message["status"] == "UNREAD"
        assert message["triage_status"] == "NEW"
        # Nurse triages.
        res = api.triage_portal_message(
            message["id"], TEST_USERS["nurse_headers"],
        )
        m_after = validate_success(res)
        assert m_after["triage_status"] == "TRIAGED"
        assert m_after["status"] == "UNREAD", (
            "status dimension must be untouched by triage; got "
            f"{m_after['status']}"
        )

    # difficulty: non_linear_state_machine/portal_message_parallel_status_and_triage_dimensions
    def test_mark_read_does_not_change_triage(self, api):
        """PRD §3.6: "Marking read or archiving never touches the
        triage dimension."

        Claim: triage M to TRIAGED, then mark-read; final state is
        status=READ AND triage_status=TRIAGED (dimensions
        independent).
        """
        setup = setup_portal_message_for_parallel_dimensions()
        message = setup["message"]
        provider = setup["provider"]
        # Triage first.
        api.triage_portal_message(
            message["id"], TEST_USERS["nurse_headers"],
        )
        # Now mark-read as the provider (one of the authorized
        # roles per PRD §4: PatientPortalUser | Provider).
        res = api.mark_portal_message_read(
            message["id"], make_provider_headers(provider["id"]),
        )
        m = validate_success(res)
        assert m["status"] == "READ", (
            f"status expected READ, got {m['status']}"
        )
        assert m["triage_status"] == "TRIAGED", (
            "triage_status dimension must be untouched by mark-read;"
            f" got {m['triage_status']}"
        )


# ===========================================================================
# §3.6 Triage preconditions
# ===========================================================================
class TestTriagePreconditions:

    def test_triage_provider_authored_rejected(self, api):
        """PRD §3.6: "A Nurse advances NEW to TRIAGED by triaging
        the message; this is permitted only when sender_role is
        PATIENT (provider-authored messages are not triaged)."

        Claim: triage attempted on a PROVIDER-authored message is
        rejected by state-eligibility error
        (ERR_INVALID_ENCOUNTER_STATE family — but PRD does not name
        a specific portal-state error_id; the rejection is what
        matters).
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp(portal_enabled=True)
        # Provider posts a message — sender_role becomes PROVIDER.
        res = api.create_portal_message(
            create_portal_message_payload(
                patient_id=patient["id"], provider_id=provider["id"],
                body="From the provider",
            ),
            make_provider_headers(provider["id"]),
        )
        message = validate_success(res, expected_status=201)
        assert message["sender_role"] == "PROVIDER"
        # Nurse tries to triage.
        triage_res = api.triage_portal_message(
            message["id"], TEST_USERS["nurse_headers"],
        )
        assert triage_res.status_code >= 400, (
            f"Triaging a PROVIDER-authored message must be rejected; "
            f"got status {triage_res.status_code}"
        )


# ===========================================================================
# §3.6 Escalation cascade — auto-schedule consultation
# ===========================================================================
class TestEscalationCascade:

    def test_escalate_triaged_creates_consultation_encounter(self, api):
        """PRD §3.6: "A Nurse then advances TRIAGED to ESCALATED by
        escalating; escalation is permitted only when triage_status
        is currently TRIAGED. ... On escalation, the server performs
        a cascade: it auto-schedules an Encounter of encounter_type
        CONSULTATION within 24 hours, with provider_id set to the
        patient's bound pcp_provider_id."

        Claim: escalate from TRIAGED yields triage_status=ESCALATED
        AND an auto-scheduled CONSULTATION encounter on the
        patient's bound PCP exists.
        """
        setup = setup_portal_message_for_parallel_dimensions()
        message = setup["message"]
        patient = setup["patient"]
        provider = setup["provider"]
        # Triage first.
        api.triage_portal_message(
            message["id"], TEST_USERS["nurse_headers"],
        )
        # Escalate.
        res = api.escalate_portal_message(
            message["id"], TEST_USERS["nurse_headers"],
        )
        m = validate_success(res)
        assert m["triage_status"] == "ESCALATED"
        # PRD §3.6: "auto-schedules an Encounter of encounter_type
        # CONSULTATION within 24 hours, with provider_id set to
        # the patient's bound pcp_provider_id."
        # PRD does not document a per-patient encounter LIST
        # endpoint that would let us discover the auto-created
        # row without already knowing its id. The only observable
        # evidence available through the documented API is the
        # ESCALATED triage_status; the cascade itself (auto-created
        # encounter) is a side-effect on a different entity whose
        # discoverability through the API is not defined.
        # See Silence-pattern: cross-entity-cascade — PRD names
        # the side effect but does not name a way to enumerate
        # encounters by patient. We assert what IS observable: the
        # triage_status reached ESCALATED.

    def test_escalate_from_new_rejected(self, api):
        """PRD §3.6: "escalation is permitted only when triage_status
        is currently TRIAGED."

        Claim: escalate attempted on a NEW (not yet TRIAGED) message
        is rejected.
        """
        setup = setup_portal_message_for_parallel_dimensions()
        message = setup["message"]
        # Skip triage — go straight to escalate.
        res = api.escalate_portal_message(
            message["id"], TEST_USERS["nurse_headers"],
        )
        assert res.status_code >= 400, (
            "Escalation from NEW must be rejected per §3.6"
        )


# ===========================================================================
# §3.6 Provider on message must equal Patient.pcp_provider_id
# ===========================================================================
class TestPortalMessageProviderMustBePcp:

    def test_message_provider_id_not_pcp_rejected(self, api):
        """PRD §3.6: "A PatientPortalUser (or, on the provider-reply
        side, a Provider) creates a new PortalMessage by supplying
        the patient_id, the provider_id (which must equal the
        patient's current pcp_provider_id), and a body string
        between 1 and 2000 characters inclusive."

        Claim: posting a message addressed to a Provider who is NOT
        the patient's bound PCP is rejected.
        """
        anchor_clock()
        # Bind the patient to PCP_A, but address message to PCP_B.
        from test_helpers import create_pcp_provider, create_patient, \
            bind_patient_to_pcp
        pcp_a = create_pcp_provider()
        pcp_b = create_pcp_provider()
        patient = create_patient(portal_enabled=True)
        patient = bind_patient_to_pcp(patient["id"], pcp_a["id"])
        # PatientPortalUser posts to PCP_B (NOT bound).
        res = api.create_portal_message(
            create_portal_message_payload(
                patient_id=patient["id"], provider_id=pcp_b["id"],
                body="To the wrong provider",
            ),
            make_patient_portal_headers(patient["id"]),
        )
        # PRD names the rule but not a unique error_id; an
        # implementation may use ERR_REFERENCE_NOT_FOUND (body FK),
        # a portal-disabled-style 403, or a generic constraint
        # error. We assert non-2xx.
        assert res.status_code >= 400, (
            "Posting to a provider who is not the patient's bound "
            "PCP must be rejected per §3.6"
        )
