"""Medical-record request lifecycle and RECEIVED cascade.

PRD §3.3.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    assert_medical_record_request,
    create_damages_multiplier,
    create_med_request,
    create_medical_record_request_payload,
    get_case,
    get_damages,
    parse_iso_date,
    patch_medical_record_request_payload,
    receive_med_request,
    reject_med_request,
    send_med_request,
    setup_case_with_fee,
    setup_records_pending,
    setup_ready_for_demand,
    validate_error,
    validate_success,
)


class TestRecordsCreationAndIntakeTransition:

    def test_create_first_request_transitions_case_to_records_pending(
        self, api,
    ):
        """PRD §3.3: "The first medical-record request created on a
        case transitions the case from INTAKE to RECORDS_PENDING only
        if the case has a ContingencyFeeAgreement and the case's
        sol_deadline is more than 30 days into the future at the
        moment of the request".

        Claim: After first request creation, Case.status ==
        RECORDS_PENDING.
        """
        _, case, _, request = setup_records_pending()
        assert_medical_record_request(request)
        # PRD §3.3: a new request enters DRAFT.
        assert request["status"] == "DRAFT"
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "RECORDS_PENDING"

    def test_dos_end_before_start_rejected_with_dos_invalid(
        self, api, paralegal_headers,
    ):
        """PRD §3.3: "the end date must be on or after the start date
        and on or after the case's incident_date, and a violation is
        rejected with ERR_DATE_OF_SERVICE_INVALID."

        Claim: dos_end < dos_start → ERR_DATE_OF_SERVICE_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        # Pick start > end
        inc = parse_iso_date(case["incident_date"])
        bad_payload = create_medical_record_request_payload(
            date_of_service_start=(inc + timedelta(days=10)).isoformat(),
            date_of_service_end=(inc + timedelta(days=5)).isoformat(),
        )
        resp = api.create_medical_record_request(
            case["id"], bad_payload, paralegal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_OF_SERVICE_INVALID.value)

    def test_dos_end_before_incident_rejected(
        self, api, paralegal_headers,
    ):
        """PRD §3.3: "the end date must be on or after the start date
        and on or after the case's incident_date".

        Claim: dos_end < incident_date → ERR_DATE_OF_SERVICE_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        inc = parse_iso_date(case["incident_date"])
        bad_payload = create_medical_record_request_payload(
            date_of_service_start=(inc - timedelta(days=10)).isoformat(),
            date_of_service_end=(inc - timedelta(days=5)).isoformat(),
        )
        resp = api.create_medical_record_request(
            case["id"], bad_payload, paralegal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_OF_SERVICE_INVALID.value)


class TestRecordsSendTransition:

    def test_send_flips_draft_to_sent_and_stamps_sent_at(
        self, api,
    ):
        """PRD §3.3: "Sending a request to its provider — a Paralegal
        action available only while the case is in RECORDS_PENDING —
        flips the request from DRAFT to SENT and stamps its sent_at to
        the server's current time."

        Claim: After send, status==SENT and sent_at is non-null.
        """
        _, _, _, request = setup_records_pending()
        # Refetch case id
        sent = send_med_request(request["case_id"], request["id"])
        assert sent["status"] == "SENT"
        assert sent["sent_at"] is not None, "sent_at must be stamped"


class TestRecordsReceivedCascade:

    def test_received_recomputes_damages_and_promotes_case(self, api):
        """PRD §3.3: "Marking a sent request as received — accomplished
        by patching its status to RECEIVED together with a
        billed_amount_cents value that must be at least zero — stamps
        received_at, persists the billed amount, recomputes
        Damages.medical_bills_cents and Damages.total_damages_cents
        (bumping Damages.version), and, if this was the last
        outstanding non-terminal request and Case.assigned_attorney_id
        is set and Damages.total_damages_cents is now greater than
        zero, advances the case from RECORDS_PENDING to
        READY_FOR_DEMAND."

        Claim: After PATCH RECEIVED with billed_amount, Case →
        READY_FOR_DEMAND, Damages.medical_bills_cents updated, Damages
        version bumped.
        """
        _, case, _, request = setup_records_pending()
        damages_before = create_damages_multiplier(
            case["id"], multiplier_value=2.0,
        )
        send_med_request(case["id"], request["id"])
        receive_med_request(case["id"], request["id"], 1_000_000)
        damages_after = get_damages(case["id"])
        # PRD §3.4: medical_bills_cents == sum of billed_amount_cents
        # over RECEIVED.
        assert damages_after["medical_bills_cents"] == 1_000_000
        # MULTIPLIER: economic=1_000_000, pain=1_000_000*2.0=2_000_000,
        # total=3_000_000
        assert damages_after["total_damages_cents"] == 3_000_000
        # Damages.version bumped
        assert damages_after["version"] > damages_before["version"]
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "READY_FOR_DEMAND", (
            "PRD §3.3: case must advance to READY_FOR_DEMAND"
        )


class TestRecordsRejected:

    def test_rejected_does_not_promote_case_if_no_received_request(
        self, api,
    ):
        """PRD §3.3: "If the provider declines, patching status to
        REJECTED records the rejection without any billed amount and
        may leave the case's state unchanged after the damages
        recomputation."

        Claim: With only one request (REJECTED), case stays in
        RECORDS_PENDING.
        """
        _, case, _, request = setup_records_pending()
        send_med_request(case["id"], request["id"])
        reject_med_request(case["id"], request["id"])
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "RECORDS_PENDING"


class TestRecordsCancellation:

    def test_delete_draft_request_returns_204(self, api):
        """PRD §3.3: "While a request remains in DRAFT it may be
        canceled (deleted), which moves it to CANCELED".
        PRD §4: DELETE returns 204.

        Claim: DELETE on DRAFT request returns 204.
        """
        _, case, _, request = setup_records_pending()
        from test_helpers import api_client, TEST_USERS
        resp = api_client.delete_medical_record_request(
            case["id"], request["id"],
            TEST_USERS["paralegal_headers"],
        )
        assert resp.status_code == 204, (
            f"Expected 204 on DELETE, got {resp.status_code}"
        )


class TestRecordsRoleAuth:

    def test_managing_partner_cannot_create_record_request(
        self, api, managing_partner_headers,
    ):
        """PRD §2.1: "If the role is recognized but is not authorized
        for the requested endpoint (per the RBAC implied by §4 and the
        workflow narratives in §3), the request is rejected with
        ERR_FORBIDDEN (HTTP 403)."

        Claim: ManagingPartner create record request → ERR_FORBIDDEN.
        PRD §4 restricts the medical-record-requests endpoints to
        Paralegal and Attorney.
        """
        _, case, _ = setup_case_with_fee()
        resp = api.create_medical_record_request(
            case["id"],
            create_medical_record_request_payload(),
            managing_partner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
