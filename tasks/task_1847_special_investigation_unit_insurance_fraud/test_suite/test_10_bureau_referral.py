"""Fraud bureau referral: deadline boundary, state-specific windows, filing."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, setup_case_closed_substantiated,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, assign_investigator,
    log_evidence, submit_evidence_review, admit_evidence,
)
from test_helpers.api_client import api_client


class TestBureauDeadlineBoundary:
    """Difficulty/boundary_precision_check/bureau_filing_deadline_strict_greater_than"""

    def _setup_ca_case_with_bureau(self, api, close_clock="2026-08-14T00:00:00Z"):
        """Close a CA case substantiated at close_clock; return ctx + bureau referral."""
        mh = make_manager_headers()
        get_success_data(api_client.set_clock(close_clock, mh))
        adj, ah = create_adjuster(manager_headers=mh)
        inv, ih = create_investigator(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=100_000_000)
        ref = create_referral(claim, red_flag_codes=["PRIOR_FRAUD_CONVICTION"],
                              headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        ev = log_evidence(case, inv, evidence_type="RECORDS",
                          materiality="SUBSTANTIVE", fraud_amount_cents=600_000,
                          collected_at="2026-08-13T00:00:00Z")
        ev = submit_evidence_review(case, ev, inv)
        ev, case = admit_evidence(case, ev, case["version"], manager_headers=mh)
        resp = api_client.submit_case_for_decision(case["id"], ih)
        case = get_success_data(resp)
        resp2 = api_client.close_case(case["id"], {"closed_reason": "SUBSTANTIATED"}, mh)
        case = validate_success(resp2)
        bur_resp = api_client.list_case_bureau_referrals(case["id"], mh)
        burs = get_success_data(bur_resp)
        assert burs, "expected auto-created bureau referral"
        return {"manager_headers": mh, "adjuster": adj, "investigator": inv,
                "claim": claim, "case": case, "bureau_referral": burs[0]}

    def test_filing_exactly_at_deadline_is_on_time(self, api):
        """PRD §3.6: "a filing exactly at `deadline_at` is on time, and the
        `late_filing` flag is set only when `filed_at` is strictly later."
        PRD §2.10: "a bureau referral filed exactly at its deadline is on time"
        CA window is 30 days from close 2026-08-14 → deadline 2026-09-13T00:00:00Z.

        Design: Difficulty/boundary_precision_check/bureau_filing_deadline_strict_greater_than
        """
        ctx = self._setup_ca_case_with_bureau(api, close_clock="2026-08-14T00:00:00Z")
        bur = ctx["bureau_referral"]
        assert bur["deadline_at"] == "2026-09-13T00:00:00Z", \
            f"expected deadline 2026-09-13T00:00:00Z, got {bur['deadline_at']}"
        # Set clock to exactly deadline
        get_success_data(api_client.set_clock("2026-09-13T00:00:00Z",
                                              ctx["manager_headers"]))
        resp = api_client.file_bureau_referral(
            ctx["case"]["id"], bur["id"],
            {"expected_referral_version": bur["version"]},
            ctx["manager_headers"])
        data = validate_success(resp)
        assert data["late_filing"] is False
        assert data["status"] == "FILED"

    def test_filing_one_second_past_deadline_is_late(self, api):
        """PRD §3.6: "the `late_filing` flag is set only when `filed_at` is
        strictly later."
        PRD §3.6: "A late referral lands in `LATE_FILED`"

        Design: Difficulty/boundary_precision_check/bureau_filing_deadline_strict_greater_than
        """
        ctx = self._setup_ca_case_with_bureau(api, close_clock="2026-08-14T00:00:00Z")
        bur = ctx["bureau_referral"]
        # Set clock 1 second past deadline
        get_success_data(api_client.set_clock("2026-09-13T00:00:01Z",
                                              ctx["manager_headers"]))
        resp = api_client.file_bureau_referral(
            ctx["case"]["id"], bur["id"],
            {"expected_referral_version": bur["version"]},
            ctx["manager_headers"])
        data = validate_success(resp)
        assert data["late_filing"] is True
        assert data["status"] == "LATE_FILED"


class TestBureauStateWindows:
    def test_fl_deadline_uses_60_day_window(self, api):
        """PRD §3.6: "The filing window depends on the claim's state: 30 days for
        California, New York, and Texas; 60 days for Florida; 45 days for New
        Jersey; and 45 days for every other state. `deadline_at` is the closure
        timestamp plus that many 86,400-second days."
        Close at 2026-08-01 → FL deadline = 2026-09-30T00:00:00Z.

        Design: Corner/calculations/bureau_deadline_uses_state_specific_window
        """
        mh = make_manager_headers()
        get_success_data(api_client.set_clock("2026-08-01T00:00:00Z", mh))
        adj, ah = create_adjuster(state_licenses=["FL"], manager_headers=mh)
        inv, ih = create_investigator(state_certifications=["FL"], manager_headers=mh)
        claim = create_claim(adj, state_code="FL", claimed_amount_cents=100_000_000)
        ref = create_referral(claim, red_flag_codes=["PRIOR_FRAUD_CONVICTION"],
                              headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        ev = log_evidence(case, inv, evidence_type="RECORDS",
                          materiality="SUBSTANTIVE", fraud_amount_cents=600_000,
                          collected_at="2026-08-01T00:00:00Z")
        ev = submit_evidence_review(case, ev, inv)
        ev, case = admit_evidence(case, ev, case["version"], manager_headers=mh)
        case = get_success_data(api_client.submit_case_for_decision(case["id"], ih))
        case = validate_success(api_client.close_case(
            case["id"], {"closed_reason": "SUBSTANTIATED"}, mh))
        burs = get_success_data(api_client.list_case_bureau_referrals(case["id"], mh))
        assert burs
        assert burs[0]["deadline_at"] == "2026-09-30T00:00:00Z", \
            f"FL 60d from 2026-08-01 → 2026-09-30, got {burs[0]['deadline_at']}"
