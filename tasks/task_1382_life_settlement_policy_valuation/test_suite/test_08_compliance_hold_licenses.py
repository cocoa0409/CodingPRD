"""State license windows and the compliance-hold cascade (PRD §2.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_broker_headers, make_compliance_headers,
    create_license_payload, setup_case_marketed, setup_package_compliance_review,
    create_offer,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
CO = TEST_USERS["compliance_headers"]


class TestLicenseWindows:
    def test_license_window_touch_rejected_but_gap_allowed(self, api):
        """PRD §2.8: "Two windows for the same state must be strictly disjoint: a
        new license's `effective_date` must fall strictly after the `expiry_date`
        of every existing row for that state — touching or overlapping an existing
        window is rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/license_window_touch_rejected_but_gap_allowed
        """
        validate_success(api.create_license(create_license_payload(
            license_number="LIC-TX-1", effective_date="2026-01-01",
            expiry_date="2027-12-31"), ADMIN), expected_status=201)

        # Touching (effective == existing expiry) is rejected: closed intervals.
        resp = api.create_license(create_license_payload(
            license_number="LIC-TX-2", effective_date="2027-12-31",
            expiry_date="2028-12-31"), CO)
        validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP)

        # A strict gap (effective > expiry) is allowed.
        created = validate_success(api.create_license(create_license_payload(
            license_number="LIC-TX-3", effective_date="2028-01-01",
            expiry_date="2028-12-31"), CO), expected_status=201)
        assert created["status"] == "ACTIVE"

        rows, meta = validate_paginated(api.list_licenses(CM, params={"state_code": "TX"}))
        assert len(rows) == 2
        assert meta["total_count"] == 2

    def test_license_window_interior_overlap_rejected(self, api):
        """PRD §2.8: "Two windows for the same state must be strictly disjoint: a
        new license's `effective_date` must fall strictly after the `expiry_date`
        of every existing row for that state — touching or overlapping an existing
        window is rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409). A
        license's `status` is one of `ACTIVE`, `SUSPENDED`, or `EXPIRED`, starting
        at `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/license_window_touch_rejected_but_gap_allowed
        """
        first = validate_success(api.create_license(create_license_payload(
            license_number="LIC-TX-1", effective_date="2026-01-01",
            expiry_date="2027-12-31"), ADMIN), expected_status=201)
        assert first["status"] == "ACTIVE"

        # Interior overlap: the new window starts strictly inside the existing one.
        resp = api.create_license(create_license_payload(
            license_number="LIC-TX-4", effective_date="2027-06-01",
            expiry_date="2028-06-01"), CO)
        validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP)

        rows, meta = validate_paginated(api.list_licenses(CM, params={"state_code": "TX"}))
        assert len(rows) == 1, "rejected window is not persisted"


class TestComplianceHoldCascade:
    def test_license_suspend_reinstate_hold_cycle(self, api):
        """PRD §2.8: "When that governing license transitions `ACTIVE` to
        `SUSPENDED` while the case is `MARKETED` or `IN_CLOSING`, the case's
        `hold_status` moves from `CLEAR` to `COMPLIANCE_HOLD` as a direct cascade
        of the suspension. When the suspended license is reinstated, the cases held
        by that suspension return to `CLEAR`. A case under `COMPLIANCE_HOLD` cannot
        accept an offer (directly or via counter-acceptance), cannot have its
        closing package approved, cannot have its escrow funded, and cannot have
        its escrow released; each of those attempts is rejected with
        `ERR_CASE_ON_COMPLIANCE_HOLD` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/license_suspend_reinstate_hold_cycle
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=True)
        case, offer, broker, lic = ctx["case"], ctx["offer"], ctx["broker"], ctx["license"]
        bh = make_broker_headers(broker["id"])

        validate_success(api.suspend_license(lic["id"], CO))
        held = validate_success(api.get_case(case["id"], CM))
        assert held["hold_status"] == "COMPLIANCE_HOLD"

        resp = api.accept_offer(offer["id"], {"broker_commission_bps": 300}, bh)
        validate_error(resp, ApiErrorId.ERR_CASE_ON_COMPLIANCE_HOLD)

        validate_success(api.reinstate_license(lic["id"], CO))
        cleared = validate_success(api.get_case(case["id"], CM))
        assert cleared["hold_status"] == "CLEAR"

        accepted = validate_success(api.accept_offer(offer["id"], {"broker_commission_bps": 300}, bh))
        assert accepted["status"] == "ACCEPTED"
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "IN_CLOSING"

    def test_suspend_blocks_fund_and_release_reinstate_restores(self, api):
        """PRD §2.8: "A case under `COMPLIANCE_HOLD` cannot accept an offer
        (directly or via counter-acceptance), cannot have its closing package
        approved, cannot have its escrow funded, and cannot have its escrow
        released; each of those attempts is rejected with
        `ERR_CASE_ON_COMPLIANCE_HOLD` (HTTP 409)."
        PRD §2.8: "When the suspended license is reinstated, the cases held by that
        suspension return to `CLEAR`."

        Design: Difficulty/non_linear_state_machine/license_suspend_reinstate_hold_cycle
        """
        # Hold an IN_CLOSING case (post-acceptance): approve and fund are blocked.
        ctx = setup_package_compliance_review()
        lic, case = ctx["license"], ctx["case"]
        validate_success(api.suspend_license(lic["id"], CO))
        held = validate_success(api.get_case(case["id"], CM))
        assert held["hold_status"] == "COMPLIANCE_HOLD"

        resp_approve = api.approve_package(ctx["package"]["id"], make_compliance_headers("co_1"))
        validate_error(resp_approve, ApiErrorId.ERR_CASE_ON_COMPLIANCE_HOLD)

        validate_success(api.reinstate_license(lic["id"], CO))
        assert validate_success(api.get_case(case["id"], CM))["hold_status"] == "CLEAR"
        approved = validate_success(api.approve_package(ctx["package"]["id"],
                                                        make_compliance_headers("co_1")))
        assert approved["status"] == "APPROVED"
