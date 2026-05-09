"""Infringement case lifecycle: report, verify-ownership, respond, escalate
(takedown cascade), resolve, dismiss (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_rights_holder,
    create_two_rights_holders,
    create_registered_work,
    create_reported_infringement,
    verify_infringement,
    respond_to_infringement,
    escalate_infringement,
    setup_under_arbitration_case,
    setup_takedown_cascade_scenario,
    create_infringement_payload,
    respond_payload,
    resolve_payload,
    list_rights_chain_events,
    list_audit_logs_filtered,
    make_rights_holder_headers,
    make_admin_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# Reporting an infringement case
# ---------------------------------------------------------------------------

class TestInfringementReporting:
    """PRD §3.8: "The reporter — who must be the work's primary_owner_id or
    one of its co_owners, otherwise ERR_FORBIDDEN — submits the work_id
    (which must be REGISTERED), the alleged_infringer_id of the suspected
    infringer, and a non-empty array evidence_doc_ids of opaque evidence
    document identifiers (an empty array is rejected with ERR_EVIDENCE_MISSING)."
    """

    def test_report_by_non_owner_rejected(self, api):
        """PRD §3.8: caller is not primary_owner / co_owner → ERR_FORBIDDEN."""
        owner = create_rights_holder(api, legal_name="Owner")
        stranger = create_rights_holder(api, legal_name="Stranger")
        alleged = create_rights_holder(api, legal_name="Alleged")
        work, _ = create_registered_work(api, owner=owner)
        # Stranger reports the case.
        headers = make_rights_holder_headers(stranger["id"])
        payload = create_infringement_payload(
            work_id=work["id"], alleged_infringer_id=alleged["id"],
        )
        resp = api.create_infringement_case(payload, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_report_with_empty_evidence_rejected(self, api):
        """PRD §3.8: empty evidence_doc_ids → ERR_EVIDENCE_MISSING.

        # difficulty: boundary_precision_check/empty_evidence_array_rejection
        """
        owner = create_rights_holder(api, legal_name="Owner")
        alleged = create_rights_holder(api, legal_name="Alleged")
        work, _ = create_registered_work(api, owner=owner)
        headers = make_rights_holder_headers(owner["id"])
        payload = create_infringement_payload(
            work_id=work["id"], alleged_infringer_id=alleged["id"],
            evidence_doc_ids=[],
        )
        resp = api.create_infringement_case(payload, headers)
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_MISSING.value)

    def test_report_with_one_evidence_succeeds(self, api):
        """PRD §3.8: a single evidence_doc_id succeeds (boundary contrast).

        # difficulty: boundary_precision_check/empty_evidence_array_rejection
        """
        owner = create_rights_holder(api, legal_name="Owner")
        alleged = create_rights_holder(api, legal_name="Alleged")
        work, _ = create_registered_work(api, owner=owner)
        headers = make_rights_holder_headers(owner["id"])
        payload = create_infringement_payload(
            work_id=work["id"], alleged_infringer_id=alleged["id"],
            evidence_doc_ids=["ev-1"],
        )
        resp = api.create_infringement_case(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert data["review_stage"] == "REPORTED"


# ---------------------------------------------------------------------------
# Verify ownership and pinned certificate
# ---------------------------------------------------------------------------

class TestVerifyOwnership:
    """PRD §3.8: "A PlatformAdmin then performs ownership verification,
    advancing review_stage from REPORTED to OWNERSHIP_VERIFIED. ... On
    success the server pins the work's current certificate_id into the
    case's pinned_certificate_id."
    """

    def test_verify_pins_certificate(self, api):
        """PRD §3.8: verify-ownership pins certificate_id from the work."""
        owner = create_rights_holder(api, legal_name="Owner")
        alleged = create_rights_holder(api, legal_name="Alleged")
        work, _ = create_registered_work(api, owner=owner)
        case = create_reported_infringement(api, work, owner, alleged)
        verified = verify_infringement(api, case)
        assert verified["review_stage"] == "OWNERSHIP_VERIFIED"
        assert verified.get("pinned_certificate_id") == work["certificate_id"], (
            f"PRD §3.8: pinned_certificate_id must equal Work.certificate_id; "
            f"expected {work['certificate_id']}, got {verified.get('pinned_certificate_id')}"
        )


# ---------------------------------------------------------------------------
# Respond — alleged_infringer only
# ---------------------------------------------------------------------------

class TestRespondToInfringement:
    """PRD §3.8: "The alleged infringer responds next, transitioning the case
    from OWNERSHIP_VERIFIED to RESPONSE_RECEIVED by submitting a
    response_text. The caller must be the alleged_infringer_id (ERR_FORBIDDEN
    otherwise)."
    """

    def test_respond_by_non_alleged_rejected(self, api):
        """PRD §3.8: only the alleged_infringer may respond → ERR_FORBIDDEN."""
        owner = create_rights_holder(api, legal_name="Owner")
        alleged = create_rights_holder(api, legal_name="Alleged")
        outsider = create_rights_holder(api, legal_name="Outsider")
        work, _ = create_registered_work(api, owner=owner)
        case = create_reported_infringement(api, work, owner, alleged)
        case = verify_infringement(api, case)
        headers = make_rights_holder_headers(outsider["id"])
        body = respond_payload(response_text="Ignored", version=case["version"])
        resp = api.respond_infringement(case["id"], body, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_respond_persists_response_text(self, api):
        """PRD §3.8: 'The submitted text is persisted into response_text.'"""
        owner = create_rights_holder(api, legal_name="Owner")
        alleged = create_rights_holder(api, legal_name="Alleged")
        work, _ = create_registered_work(api, owner=owner)
        case = create_reported_infringement(api, work, owner, alleged)
        case = verify_infringement(api, case)
        case = respond_to_infringement(api, case, alleged,
                                          response_text="I dispute this claim.")
        assert case["review_stage"] == "RESPONSE_RECEIVED"
        assert case["response_text"] == "I dispute this claim."


# ---------------------------------------------------------------------------
# Escalation triggers takedown cascade
# ---------------------------------------------------------------------------

class TestEscalationCascade:
    """PRD §3.8: "The takedown cascade fires on the escalation transition.
    For every EFFECTIVE license whose work_id equals the case's work_id and
    whose licensee_id equals the case's alleged_infringer_id, the server
    flips the license's status to TERMINATED and appends a RightsChainEvent
    of LICENSE_TERMINATED whose payload.reason is TAKEDOWN. ... Then, for
    every EFFECTIVE Contract whose license_id is that license's id, the
    server flips the contract's status to TERMINATED."
    """

    def test_escalation_terminates_license_and_contract(self, api):
        """PRD §3.8: depth-3 cascade Case→License→Contract.

        # difficulty: transitive_cascade/takedown_cascade_depth_three
        """
        scenario = setup_takedown_cascade_scenario(api)
        case = scenario["case"]
        licensor = scenario["licensor"]
        license_data = scenario["license"]
        contract = scenario["contract"]
        work = scenario["work"]

        # Sanity preconditions before escalation
        assert case["review_stage"] == "RESPONSE_RECEIVED"
        assert license_data["status"] == "EFFECTIVE"
        assert contract["status"] == "EFFECTIVE"

        # Escalate (caller=reporter=licensor)
        escalated = escalate_infringement(api, case, licensor)
        assert escalated["review_stage"] == "UNDER_ARBITRATION"
        assert escalated.get("takedown_issued_at") is not None, (
            "PRD §3.8: 'it stamps takedown_issued_at with the current instant.'"
        )

        # License now TERMINATED
        license_after = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert license_after["status"] == "TERMINATED"

        # Contract cascaded to TERMINATED
        contract_after = api.get_contract(contract["id"], ADMIN_HEADERS).json()["data"]
        assert contract_after["status"] == "TERMINATED"

        # RightsChainEvent LICENSE_TERMINATED with payload.reason=TAKEDOWN
        events = list_rights_chain_events(api, work["id"])
        takedown_events = [
            e for e in events
            if e["event_type"] == "LICENSE_TERMINATED"
            and (e.get("payload") or {}).get("reason") == "TAKEDOWN"
        ]
        assert len(takedown_events) >= 1, (
            "PRD §3.8: 'appends a RightsChainEvent of LICENSE_TERMINATED whose "
            "payload.reason is TAKEDOWN.'"
        )

    def test_escalation_writes_audit_log_dispute_logged(self, api):
        """PRD §3.8: 'an AuditLog row is appended at each hop of the cascade,
        including the case's own DISPUTE_LOGGED entry for the escalation.'

        # difficulty: transitive_cascade/takedown_cascade_depth_three
        """
        scenario = setup_takedown_cascade_scenario(api)
        case = scenario["case"]
        licensor = scenario["licensor"]
        escalate_infringement(api, case, licensor)
        logs = list_audit_logs_filtered(api,
                                          subject_entity="InfringementCase",
                                          subject_id=case["id"],
                                          change_type="DISPUTE_LOGGED")
        assert len(logs) >= 1, (
            "PRD §3.8: escalation must write an AuditLog row of DISPUTE_LOGGED "
            "for the InfringementCase subject"
        )

    def test_escalate_by_non_reporter_rejected(self, api):
        """PRD §3.8: 'Escalation is restricted to the reporter_id.'"""
        scenario = setup_takedown_cascade_scenario(api)
        case = scenario["case"]
        alleged = scenario["alleged_infringer"]
        # Alleged infringer attempts to escalate (must be reporter only).
        headers = make_rights_holder_headers(alleged["id"])
        resp = api.escalate_infringement(case["id"], headers,
                                           payload={"version": case["version"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Resolve and dismiss
# ---------------------------------------------------------------------------

class TestResolveAndDismiss:
    """PRD §3.8: "Resolution by the reporter sets a non-negative
    compensation_cents (a missing or negative value is rejected with
    ERR_COMPENSATION_INVALID), appends a RightsChainEvent of event_type
    INFRINGEMENT_RESOLVED whose payload carries the compensation amount,
    and writes an AuditLog of DISPUTE_LOGGED."
    """

    def test_resolve_negative_compensation_rejected(self, api):
        """PRD §3.8: compensation_cents negative → ERR_COMPENSATION_INVALID."""
        scenario = setup_under_arbitration_case(api)
        reporter = scenario["reporter"]
        case = scenario["case"]
        headers = make_rights_holder_headers(reporter["id"])
        body = resolve_payload(compensation_cents=-1, version=case["version"])
        resp = api.resolve_infringement(case["id"], body, headers)
        validate_error(resp, ApiErrorId.ERR_COMPENSATION_INVALID.value)

    def test_resolve_with_compensation_succeeds(self, api):
        """PRD §3.8: 'Resolution by the reporter sets a non-negative
        compensation_cents ... appends a RightsChainEvent of event_type
        INFRINGEMENT_RESOLVED whose payload carries the compensation amount.'"""
        scenario = setup_under_arbitration_case(api)
        reporter = scenario["reporter"]
        work = scenario["work"]
        case = scenario["case"]
        headers = make_rights_holder_headers(reporter["id"])
        body = resolve_payload(compensation_cents=10_000, version=case["version"])
        resp = api.resolve_infringement(case["id"], body, headers)
        data = validate_success(resp)
        assert data["review_stage"] == "RESOLVED"
        assert data["compensation_cents"] == 10_000
        # Rights chain records INFRINGEMENT_RESOLVED with compensation in payload.
        events = list_rights_chain_events(api, work["id"])
        resolved = [
            e for e in events
            if e["event_type"] == "INFRINGEMENT_RESOLVED"
            and (e.get("payload") or {}).get("compensation_cents") == 10_000
        ]
        assert len(resolved) >= 1, (
            "PRD §3.8: 'appends a RightsChainEvent of event_type "
            "INFRINGEMENT_RESOLVED whose payload carries the compensation amount.'"
        )

    def test_dismiss_from_reported_by_reporter(self, api):
        """PRD §3.8: 'the reporter alone may dismiss the case from REPORTED
        to the terminal DISMISSED state.'"""
        owner = create_rights_holder(api, legal_name="Owner")
        alleged = create_rights_holder(api, legal_name="Alleged")
        work, _ = create_registered_work(api, owner=owner)
        case = create_reported_infringement(api, work, owner, alleged)
        headers = make_rights_holder_headers(owner["id"])
        resp = api.dismiss_infringement(case["id"], headers,
                                          payload={"version": case["version"]})
        data = validate_success(resp)
        assert data["review_stage"] == "DISMISSED"

    def test_dismiss_from_reported_by_non_reporter_rejected(self, api):
        """PRD §3.8: only reporter may dismiss from REPORTED → ERR_FORBIDDEN."""
        owner = create_rights_holder(api, legal_name="Owner")
        alleged = create_rights_holder(api, legal_name="Alleged")
        work, _ = create_registered_work(api, owner=owner)
        case = create_reported_infringement(api, work, owner, alleged)
        headers = make_rights_holder_headers(alleged["id"])
        resp = api.dismiss_infringement(case["id"], headers,
                                          payload={"version": case["version"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
