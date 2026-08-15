"""Cascading side effects: KYC approval/rejection, attestation expiry sweep."""
from test_helpers import (
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_kyc_case_payload,
    create_accreditation_payload,
    create_subscription_payload,
    get_investor,
    get_subscription,
    make_investor_headers,
    validate_success,
)


class TestKycApproveCascade:
    def test_cascading_kyc_approval_to_subscription_unblock(
        self,
        api,
        fund_admin_headers,
        compliance_officer_headers,
        transfer_agent_headers,
    ):
        """PRD §3.2: "Approving a case from either IN_REVIEW or ESCALATED
        sets the investor's kyc_status to APPROVED and, as a cascade,
        transitions any of that investor's subscriptions currently sitting
        in KYC_HOLD into COMPLIANCE_APPROVED."

        Design: Corner/cross_cutting_layers/cascading_kyc_approval_to_subscription_unblock
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(
                fund["id"],
                create_share_class_payload(
                    min_initial_investment_cents=100, min_additional_investment_cents=50
                ),
                fund_admin_headers,
            ),
            201,
        )
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        kyc = validate_success(
            api.create_kyc_case(
                inv["id"], create_kyc_case_payload(risk_rating="LOW"), compliance_officer_headers
            ),
            201,
        )
        sub = validate_success(
            api.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=500, funding_deadline_utc="2026-08-10T00:00:00Z",
                ),
                fund_admin_headers,
            ),
            201,
        )
        api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)

        # Drive KycCase to IN_REVIEW by submitting required docs.
        for doc in kyc["required_documents"]:
            api.submit_kyc_document(
                inv["id"], kyc["id"],
                {"document_type": doc, "document_reference": f"ref-{doc}"},
                transfer_agent_headers,
            )
        api.approve_kyc_case(inv["id"], kyc["id"], {}, compliance_officer_headers)

        inv_after = get_investor(inv["id"])
        assert inv_after["kyc_status"] == "APPROVED"

        sub_after = get_subscription(fund["id"], sub["id"])
        # The subscription must have progressed out of KYC_HOLD.
        assert sub_after["status"] in ("COMPLIANCE_APPROVED", "SUBMITTED", "FUNDING_PARTIAL", "FUNDED", "ACCEPTED")


class TestAttestationExpirySweep:
    def test_scheduled_attestation_expiry_on_clock_advance(
        self, api, fund_admin_headers, compliance_officer_headers
    ):
        """PRD §3.3: "When the logical clock passes an attestation's
        expires_at_utc, the attestation transitions from VERIFIED to EXPIRED,
        the investor's accreditation_status is recomputed to the next-highest
        still-valid tier (or to UNVERIFIED if no valid attestation remains)."

        Design: Corner/cross_cutting_layers/scheduled_attestation_expiry_on_clock_advance
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        investor_headers = make_investor_headers(inv["id"])
        att = validate_success(
            api.create_accreditation(
                inv["id"],
                create_accreditation_payload(
                    attestation_tier="ACCREDITED",
                    evidence_type="CPA_LETTER",
                    evidence_document_id="doc1",
                    attested_at_utc="2026-08-01T00:00:00Z",
                ),
                investor_headers,
            ),
            201,
        )
        api.verify_accreditation(inv["id"], att["id"], compliance_officer_headers)

        # Advance clock past expires_at_utc (attested_at + 365 days = 2027-08-01).
        api.set_current_utc({"to_iso8601": "2027-09-01T00:00:00Z"}, fund_admin_headers)

        att_after = validate_success(
            api.get_accreditation(inv["id"], att["id"], fund_admin_headers), 200
        )
        assert att_after["status"] == "EXPIRED"

        inv_after = get_investor(inv["id"])
        assert inv_after["accreditation_status"] == "UNVERIFIED"
