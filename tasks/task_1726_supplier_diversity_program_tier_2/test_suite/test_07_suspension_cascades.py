"""Supplier suspension cascades: admin-triggered and audit-failure-triggered
withdrawal of invitations and diverse_bid_count recomputation."""
from test_helpers import (
    TEST_USERS,
    create_business_unit,
    create_open_event_with_bidder,
    create_sourcing_event,
    create_supplier_with_verified_cert,
    get_success_data,
    invite_supplier,
    open_audit_case,
    open_sourcing_event,
    record_audit_outcome,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
LEAD1 = TEST_USERS["lead_1_headers"]


class TestAuditFailureCascade:
    def _setup_cascade_scenario(self, api):
        """ACTIVE diverse supplier (VERIFIED SELF_CERT) invited and
        BID_SUBMITTED on an OPEN event requiring 1 diverse bidder, plus an
        OPEN audit case owned by auditor-9."""
        bu = create_business_unit(inclusion_min_diverse_bidders=1)
        supplier, cert = create_supplier_with_verified_cert(
            legal_name="Cascade Co", tax_id="T-CAS", cert_type="SELF_CERT",
            certificate_number="SC-9")
        event, invitation = create_open_event_with_bidder(
            bu["id"], supplier["id"], title="Bracket fabrication",
            estimated_value_cents=500000, required_diverse_bidders=1)
        case = open_audit_case(supplier["id"], cert["id"])
        return supplier, cert, event, invitation, case

    def test_audit_failure_revokes_cert_and_suspends_supplier(self, api):
        """PRD §3.9: "A `FAILED` outcome fires the revocation cascade. The
        audited certification moves from `VERIFIED` to `REVOKED` — this is
        the only producer of `REVOKED` in the system. The revocation in turn
        suspends the supplier: an `ACTIVE` supplier moves to `SUSPENDED` via
        the same system-triggered transition as a manual suspension"
        PRD §3.10: "`risk_score_standard` weighs confirmed findings only: 40
        points per failed audit plus 10 points per expired-unrenewed
        certification, capped at 100."

        Design: Difficulty/transitive_cascade/audit_failure_cascade_to_event_bid_count
        """
        supplier, cert, _event, _inv, case = self._setup_cascade_scenario(api)
        record_audit_outcome(case["id"], "FAILED")
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "REVOKED", (
            "Link 1: the FAILED outcome mutated the certification"
        )
        stored = validate_success(api.get_supplier(supplier["id"], ADMIN1))
        assert stored["status"] == "SUSPENDED", (
            "Link 2: the revocation suspended the supplier"
        )
        assert stored["diverse_eligible"] is False
        assert stored["risk_score_standard"] == 40, (
            "One FAILED audit contributes the 40-point term"
        )

    def test_audit_failure_withdraws_bid_and_recomputes_count(self, api):
        """PRD §3.9: "The revocation in turn suspends the supplier: an
        `ACTIVE` supplier moves to `SUSPENDED` via the same system-triggered
        transition as a manual suspension, with the same withdrawal cascade —
        every invitation in `INVITED` or `BID_SUBMITTED` becomes `WITHDRAWN`,
        each withdrawal recomputing its event's `diverse_bid_count`."
        PRD §3.7: "The `diverse_bid_count` on a sourcing event is a
        denormalized count of that event's invitations currently in
        `BID_SUBMITTED` whose supplier is currently `diverse_eligible`."

        Design: Difficulty/transitive_cascade/audit_failure_cascade_to_event_bid_count
        """
        supplier, _cert, event, invitation, case = (
            self._setup_cascade_scenario(api))
        pre = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert pre["diverse_bid_count"] == 1, (
            "The BID_SUBMITTED diverse-eligible supplier counts before the "
            "outcome"
        )
        record_audit_outcome(case["id"], "FAILED")
        invs, _meta = validate_paginated(
            api.list_event_invitations(event["id"], LEAD1))
        assert invs[0]["id"] == invitation["id"]
        assert invs[0]["status"] == "WITHDRAWN", (
            "Link 3: the suspension withdrew the BID_SUBMITTED invitation"
        )
        post = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert post["diverse_bid_count"] == 0, (
            "Link 4: the withdrawal recomputed the event's diverse_bid_count"
        )


class TestAdminSuspensionCascade:
    def test_admin_suspend_withdraws_submitted_bid(self, api):
        """PRD §3.1: "Suspension has a deliberate withdrawal cascade: every
        `BidderInvitation` for that supplier currently in `INVITED` or
        `BID_SUBMITTED` moves to `WITHDRAWN`, and each of those withdrawals
        recomputes the owning sourcing event's `diverse_bid_count`."

        Design: Difficulty/transitive_cascade/admin_suspension_cascade_to_event_bid_count
        """
        bu = create_business_unit(inclusion_min_diverse_bidders=1)
        supplier, _cert = create_supplier_with_verified_cert(
            legal_name="Vet Works", tax_id="T-VET", cert_type="VET",
            certificate_number="V-1")
        event, invitation = create_open_event_with_bidder(
            bu["id"], supplier["id"], title="Grounds maintenance",
            estimated_value_cents=300000, required_diverse_bidders=1)
        pre = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert pre["diverse_bid_count"] == 1
        suspended = validate_success(api.suspend_supplier(supplier["id"],
                                                          ADMIN1))
        assert suspended["status"] == "SUSPENDED"
        invs, _meta = validate_paginated(
            api.list_event_invitations(event["id"], ADMIN1))
        assert invs[0]["id"] == invitation["id"]
        assert invs[0]["status"] == "WITHDRAWN", (
            "Link 1: the suspension mutated the BID_SUBMITTED invitation"
        )
        post = validate_success(api.get_sourcing_event(event["id"], ADMIN1))
        assert post["diverse_bid_count"] == 0, (
            "Link 2: the withdrawal recomputed diverse_bid_count from 1 to 0"
        )

    def test_admin_suspend_withdraws_pending_invitation(self, api):
        """PRD §3.1: "Suspension has a deliberate withdrawal cascade: every
        `BidderInvitation` for that supplier currently in `INVITED` or
        `BID_SUBMITTED` moves to `WITHDRAWN`, and each of those withdrawals
        recomputes the owning sourcing event's `diverse_bid_count`."

        Design: Difficulty/transitive_cascade/admin_suspension_cascade_to_event_bid_count
        """
        bu = create_business_unit()
        supplier, _cert = create_supplier_with_verified_cert(
            legal_name="Vet Works", tax_id="T-VET", cert_type="VET",
            certificate_number="V-1")
        event = create_sourcing_event(bu["id"], title="Pending invite",
                                      required_diverse_bidders=0)
        open_sourcing_event(event["id"])
        invitation = invite_supplier(event["id"], supplier["id"])
        assert invitation["status"] == "INVITED"
        suspended = validate_success(
            api.suspend_supplier(supplier["id"], ADMIN1))
        assert suspended["status"] == "SUSPENDED"
        invs, _meta = validate_paginated(
            api.list_event_invitations(event["id"], ADMIN1))
        assert invs[0]["status"] == "WITHDRAWN", (
            "The INVITED invitation is withdrawn by the same cascade"
        )
