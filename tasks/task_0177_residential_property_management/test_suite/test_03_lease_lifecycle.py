"""Lease and applicant state-machine depth tests.

The renewal-offer cycle, the screened-applicant fork, and the lease-sign cascade
that mints a tenant and consumes the applicant.
"""
import pytest
from test_helpers import get_success_data
from test_helpers.fixtures import (
    PM, create_unit, create_screened_applicant, setup_active_lease,
    setup_draft_lease_ready_to_sign,
)
from test_helpers.api_client import api_client


class TestRenewalOfferCycle:
    def test_offer_then_retract_returns_to_active(self, api):
        """PRD §3.4: "A PropertyManager may extend a renewal offer on a lease that
        is ACTIVE, moving it to RENEWAL_OFFERED; the same operation, invoked on a
        lease already in RENEWAL_OFFERED, retracts the standing offer and returns
        the lease to ACTIVE."

        Design: Difficulty/non_linear_state_machine/lease_renewal_offer_cycle
        """
        world = setup_active_lease()
        lease = world["lease"]
        v_signed = lease["version"]
        offered = get_success_data(api.offer_renewal(
            lease["id"], {"expected_lease_version": v_signed}, PM))
        assert offered["status"] == "RENEWAL_OFFERED"
        retracted = get_success_data(api.offer_renewal(
            lease["id"], {"expected_lease_version": offered["version"]}, PM))
        assert retracted["status"] == "ACTIVE"

    def test_version_increments_on_each_toggle(self, api):
        """PRD §3.4: "Either direction of the toggle requires expected_lease_version
        to match the lease's current version, failing which the request is rejected
        with ERR_STALE_VERSION, and either direction increments the lease's version
        by one."

        Design: Difficulty/non_linear_state_machine/lease_renewal_offer_cycle
        """
        world = setup_active_lease()
        lease = world["lease"]
        v_signed = lease["version"]
        offered = get_success_data(api.offer_renewal(
            lease["id"], {"expected_lease_version": v_signed}, PM))
        assert offered["version"] > v_signed
        retracted = get_success_data(api.offer_renewal(
            lease["id"], {"expected_lease_version": offered["version"]}, PM))
        assert retracted["version"] > offered["version"]


class TestScreenedFork:
    def test_approve_branch_moves_to_approved(self, api):
        """PRD §3.2: "Approval moves the application to APPROVED, but only if two
        conditions hold: the screening decision must be PASS ... and the unit named
        by the application's unit_id must currently be VACANT_READY".

        Design: Difficulty/non_linear_state_machine/applicant_screened_fork_approve_or_deny
        """
        unit = create_unit(market_rent_cents=200000)
        app = create_screened_applicant(unit["id"], annual_income_cents=12000000,
                                        credit_score=700, requested_rent_cents=200000)
        decided = get_success_data(api.decide_applicant(
            app["id"], {"decision": "APPROVE"}, PM))
        assert decided["status"] == "APPROVED"

    def test_deny_branch_moves_to_denied(self, api):
        """PRD §3.2: "A DENY decision moves a screened application to DENIED, which
        is terminal."

        Design: Difficulty/non_linear_state_machine/applicant_screened_fork_approve_or_deny
        """
        unit = create_unit(market_rent_cents=200000)
        app = create_screened_applicant(unit["id"], annual_income_cents=12000000,
                                        credit_score=700, requested_rent_cents=200000)
        decided = get_success_data(api.decide_applicant(
            app["id"], {"decision": "DENY"}, PM))
        assert decided["status"] == "DENIED"


class TestSignCascade:
    def test_sign_mints_tenant_and_sets_pointer(self, api):
        """PRD §3.3: "For an original lease, the system mints a Tenant from the
        source applicant and sets the lease's tenant_id to that new tenant".
        PRD §3.3: "Signing is performed by a PropertyManager and advances the lease
        from DRAFT to ACTIVE."

        Design: Difficulty/transitive_cascade/lease_sign_mints_tenant_leases_applicant
        """
        ready = setup_draft_lease_ready_to_sign()
        signed = get_success_data(api.sign_lease(ready["lease"]["id"], PM))
        assert signed["status"] == "ACTIVE"
        assert signed["tenant_id"] is not None
        tenant = get_success_data(api.get_tenant(signed["tenant_id"], PM))
        assert tenant["status"] == "CURRENT"

    def test_sign_advances_applicant_to_leased(self, api):
        """PRD §3.3: "For an original lease, the source application is advanced to
        LEASED, driven by the lease activation."

        Design: Difficulty/transitive_cascade/lease_sign_mints_tenant_leases_applicant
        """
        ready = setup_draft_lease_ready_to_sign()
        signed = get_success_data(api.sign_lease(ready["lease"]["id"], PM))
        applicant = get_success_data(api.get_applicant(ready["applicant"]["id"], PM))
        assert applicant["status"] == "LEASED"
        assert signed["tenant_id"] is not None
