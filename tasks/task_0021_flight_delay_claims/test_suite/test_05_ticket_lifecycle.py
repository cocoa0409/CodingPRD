"""Ticket creation, change/confirm/refund, PNR uniqueness (PRD §3.3)."""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    TicketStatus,
    create_insurer,
    create_policy,
    create_flight,
    create_ticket,
    create_ticket_payload,
    setup_basic_insurer_with_policy,
    setup_ticket_attached,
    setup_basic_claim_in_matched,
    setup_claim_approved,
    setup_claim_in_executing,
    setup_claim_paid,
    get_ticket,
    assert_ticket,
    unique_doc_id,
    unique_pnr,
)


class TestTicketAutoMatch:
    def test_auto_match_to_unique_active_policy(self, api, policy_admin_headers):
        """PRD §3.3: "if exactly one ACTIVE policy in the insurer has
        policy_holder_doc_id equal to passenger_doc_id, the ticket is bound
        to that policy with status set to ATTACHED and
        scheduled_departure_epoch_ms and scheduled_arrival_epoch_ms
        snapshotted from the flight."

        Claim: ticket ingest (no policy_id) with matching doc → ATTACHED.
        """
        insurer, policy = setup_basic_insurer_with_policy()
        flight = create_flight(insurer["id"])
        resp = api.create_ticket(
            insurer["id"],
            create_ticket_payload(
                flight_id=flight["id"],
                passenger_doc_id=policy["policy_holder_doc_id"],
                passenger_name=policy["policy_holder_name"],
            ),
            policy_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_ticket(data)
        assert data["status"] == TicketStatus.ATTACHED.value
        assert data["policy_id"] == policy["id"]
        assert data["scheduled_departure_epoch_ms"] == flight["scheduled_departure_epoch_ms"]
        assert data["scheduled_arrival_epoch_ms"] == flight["scheduled_arrival_epoch_ms"]

    def test_no_match_results_in_unmatched(self, api, policy_admin_headers):
        """PRD §3.3: "If no policy matches, the ticket is recorded with
        status set to UNMATCHED and a ManualReviewCase is opened with
        failure_reason set to NO_POLICY_FOUND."

        Claim: ticket with unknown doc → status=UNMATCHED.
        """
        insurer, policy = setup_basic_insurer_with_policy()
        flight = create_flight(insurer["id"])
        resp = api.create_ticket(
            insurer["id"],
            create_ticket_payload(
                flight_id=flight["id"],
                passenger_doc_id=unique_doc_id(),  # mismatch
            ),
            policy_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == TicketStatus.UNMATCHED.value


class TestPnrUniqueness:
    def test_duplicate_pnr_among_attached_tickets_rejected(self, api, policy_admin_headers):
        """PRD §3.3: "Ticket uniqueness is enforced on the pair (insurer_id,
        pnr_code) whenever the ticket's status is ATTACHED or CHANGED; a
        duplicate is rejected with ERR_DUPLICATE_PNR (HTTP 409)."

        Claim: creating a 2nd ATTACHED ticket with the same PNR fails with
        ERR_DUPLICATE_PNR.
        """
        insurer, policy = setup_basic_insurer_with_policy()
        flight = create_flight(insurer["id"])
        pnr = unique_pnr()
        # First ticket — succeeds, ATTACHED.
        first = api.create_ticket(
            insurer["id"],
            create_ticket_payload(
                flight_id=flight["id"],
                passenger_doc_id=policy["policy_holder_doc_id"],
                passenger_name=policy["policy_holder_name"],
                pnr_code=pnr,
            ),
            policy_admin_headers,
        )
        validate_success(first, expected_status=201)
        # Second ticket reusing the same PNR while first is ATTACHED → 409.
        dup = api.create_ticket(
            insurer["id"],
            create_ticket_payload(
                flight_id=flight["id"],
                passenger_doc_id=policy["policy_holder_doc_id"],
                passenger_name=policy["policy_holder_name"],
                pnr_code=pnr,
            ),
            policy_admin_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_PNR.value)


class TestTicketChangeConfirm:
    def test_change_resnapshots_schedule(self, api, policy_admin_headers):
        """PRD §3.3: "A passenger whose itinerary changes is captured by the
        ATTACHED → CHANGED revision: the PolicyAdmin provides a new
        flight_id and the ticket re-snapshots its scheduled departure and
        scheduled arrival from the new flight".

        Claim: change to a new flight updates schedule and sets status=CHANGED.
        """
        ctx = setup_ticket_attached()
        insurer, ticket = ctx["insurer"], ctx["ticket"]
        new_flight = create_flight(
            insurer["id"],
            scheduled_departure_epoch_ms=20_000_000,
            scheduled_arrival_epoch_ms=25_000_000,
        )
        resp = api.change_ticket(
            insurer["id"], ticket["id"],
            {"flight_id": new_flight["id"]},
            policy_admin_headers,
        )
        data = validate_success(resp)
        assert data["status"] == TicketStatus.CHANGED.value
        assert data["flight_id"] == new_flight["id"]
        assert data["scheduled_departure_epoch_ms"] == new_flight["scheduled_departure_epoch_ms"]
        assert data["scheduled_arrival_epoch_ms"] == new_flight["scheduled_arrival_epoch_ms"]

    def test_confirm_returns_changed_ticket_to_attached(self, api, policy_admin_headers):
        """PRD §3.3: "A subsequent confirm operation by the same role
        transitions the ticket back from CHANGED to ATTACHED with no further
        side effects, allowing multiple change-confirm rounds."

        Claim: confirm on a CHANGED ticket → ATTACHED.
        """
        ctx = setup_ticket_attached()
        insurer, ticket = ctx["insurer"], ctx["ticket"]
        f2 = create_flight(insurer["id"])
        change = api.change_ticket(
            insurer["id"], ticket["id"], {"flight_id": f2["id"]},
            policy_admin_headers,
        )
        validate_success(change)
        confirm = api.confirm_ticket(insurer["id"], ticket["id"], policy_admin_headers)
        data = validate_success(confirm)
        assert data["status"] == TicketStatus.ATTACHED.value


class TestTicketRefund:
    def test_refund_attached_ticket(self, api, policy_admin_headers):
        """PRD §3.3: "A refund operation by a PolicyAdmin drives the ticket
        from ATTACHED (or CHANGED) into REFUNDED".

        Claim: refund on ATTACHED ticket → REFUNDED.
        """
        ctx = setup_ticket_attached()
        resp = api.refund_ticket(
            ctx["insurer"]["id"], ctx["ticket"]["id"], policy_admin_headers,
        )
        data = validate_success(resp)
        assert data["status"] == TicketStatus.REFUNDED.value

    def test_refund_blocked_when_claim_approved(self, api, policy_admin_headers):
        """PRD §3.3: "is rejected with ERR_TICKET_LOCKED_BY_CLAIM if a claim
        referencing this ticket is in APPROVED, EXECUTING, or PAID."

        Claim: refund attempt while a referencing claim is APPROVED →
        ERR_TICKET_LOCKED_BY_CLAIM.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved()
        resp = api.refund_ticket(insurer["id"], ticket["id"], policy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_TICKET_LOCKED_BY_CLAIM.value)

    def test_change_blocked_while_claim_under_review(self, api, policy_admin_headers):
        """PRD §3.3: "this fails ... with ERR_TICKET_LOCKED_BY_CLAIM if any
        claim referencing the ticket is currently in UNDER_REVIEW or
        APPROVED review status."

        Claim: change a ticket while a claim referencing it is UNDER_REVIEW
        → ERR_TICKET_LOCKED_BY_CLAIM.
        """
        from test_helpers import setup_claim_under_review
        insurer, policy, flight, ticket, claim_uw, _rid = setup_claim_under_review()
        new_flight = create_flight(
            insurer["id"],
            scheduled_departure_epoch_ms=20_000_000,
            scheduled_arrival_epoch_ms=25_000_000,
        )
        resp = api.change_ticket(
            insurer["id"], ticket["id"],
            {"flight_id": new_flight["id"]},
            policy_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TICKET_LOCKED_BY_CLAIM.value)
