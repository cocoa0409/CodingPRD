"""Vendor lifecycle (the AUTHORIZED<->SUSPENDED cyclic loop and termination) and
assorted state-machine guards on certification and vendor (PRD §3.9, §3.6).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_agency,
    create_authorized_vendor,
    setup_suspended_vendor,
    setup_certified_participant,
    CLERK,
    CPA,
)


class TestVendorCyclicLoop:
    def test_violation_at_threshold_auto_suspends(self, api):
        """PRD §3.9: "When the cumulative violation_points reaches or exceeds the
        suspension threshold of 100, the vendor is automatically moved from
        AUTHORIZED to SUSPENDED; the boundary is inclusive, so exactly 100 points
        triggers suspension."

        Design: Difficulty/non_linear_state_machine/vendor_cyclic_authorize_suspend_reinstate
        """
        agency = create_agency()
        vendor = create_authorized_vendor(agency["id"], legal_name="Grocer Two",
                                          peer_group="LARGE")
        v = validate_success(api.record_vendor_violation(vendor["id"], 100, CLERK))
        assert v["status"] == "SUSPENDED"
        assert v["violation_points"] == 100

    def test_reinstate_returns_to_authorized_and_resets_points(self, api):
        """PRD §3.9: "A SUSPENDED vendor is reinstated by a clerk back to
        AUTHORIZED, and reinstatement resets the vendor's violation_points to 0".

        Design: Difficulty/non_linear_state_machine/vendor_cyclic_authorize_suspend_reinstate
        """
        ctx = setup_suspended_vendor(points=100, peer_group="LARGE")
        assert ctx["vendor"]["status"] == "SUSPENDED"
        v = validate_success(api.reinstate_vendor(ctx["vendor"]["id"], CLERK))
        assert v["status"] == "AUTHORIZED"
        assert v["violation_points"] == 0


class TestVendorStateGuards:
    def test_terminated_vendor_cannot_be_authorized(self, api):
        """PRD §3.9: "A PENDING vendor is authorized — moving to AUTHORIZED — only
        from PENDING (otherwise ERR_INVALID_STATE)."
        PRD §3.9: "A vendor in either AUTHORIZED or SUSPENDED status can be
        terminated, moving it permanently to TERMINATED (any other starting state
        yields ERR_INVALID_STATE); termination is final."

        Design: Corner/state_machines/terminal_vendor_cannot_authorize
        """
        agency = create_agency()
        vendor = create_authorized_vendor(agency["id"], legal_name="Term Vendor",
                                          peer_group="SMALL")
        validate_success(api.terminate_vendor(vendor["id"], CLERK))
        resp = api.authorize_vendor(vendor["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestCertificationStateGuards:
    def test_suspend_already_suspended_certification_rejected(self, api):
        """PRD §3.6: "A CPA suspends an ACTIVE certification (otherwise
        ERR_INVALID_STATE), moving it to SUSPENDED."

        Design: Corner/state_machines/suspend_already_suspended_certification_invalid_state
        """
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="5551",
        )
        cert_id = ctx["certification"]["id"]
        validate_success(api.suspend_certification(cert_id, CPA))
        resp = api.suspend_certification(cert_id, CPA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_reinstate_after_period_ended_rejected(self, api):
        """PRD §3.6: "A CPA reinstates a SUSPENDED certification (otherwise
        ERR_INVALID_STATE), but only while the agency's current_utc is strictly
        before the certification's period_end_utc; a reinstatement attempted on or
        after the period end is rejected with ERR_CERT_PERIOD_ENDED."

        Design: Corner/state_machines/reinstate_after_period_ended_rejected
        """
        # POSTPARTUM cert (180 days) from 2026-01-01, suspended, then clock past end.
        ctx = setup_certified_participant(
            category="POSTPARTUM", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=0, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")],
            clock_iso="2026-01-01T00:00:00.000Z", ssn_last4="5552",
        )
        cert_id = ctx["certification"]["id"]
        agency_id = ctx["agency_id"]
        validate_success(api.suspend_certification(cert_id, CPA))
        validate_success(api.set_current_utc(agency_id, "2027-01-01T00:00:00.000Z", CLERK))
        resp = api.reinstate_certification(cert_id, CPA)
        validate_error(resp, ApiErrorId.ERR_CERT_PERIOD_ENDED.value)
