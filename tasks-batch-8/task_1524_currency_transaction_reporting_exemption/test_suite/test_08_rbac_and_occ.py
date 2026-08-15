"""RBAC (PRD §2.1, §4) and optimistic-concurrency rules (PRD §2.9)."""
from test_helpers import (
    ApiErrorId,
    create_active_phase_i_exemption,
    create_ctr_in_draft,
    create_validated_ctr,
    get_success_data,
    make_analyst_headers,
    make_examiner_headers,
    make_manager_headers,
    make_officer_headers,
    make_teller_headers,
    request_exemption,
    set_clock,
    setup_branch_and_customer,
    alert_in_status,
    api_client,
    validate_error,
    validate_success,
)


class TestRbacExclusiveDenials:
    def test_rbac_teller_cannot_file_ctr_returns_unauthorized(self, api):
        """PRD §4 endpoint table: `POST /ctrs/{id}/file` — Authorized Role(s):
        `BSAOfficer`.
        PRD §2.1: "A request whose authenticated role is not in the target
        endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_teller_cannot_file_ctr_returns_unauthorized
        """
        branch, customer = setup_branch_and_customer()
        ctr = create_validated_ctr(customer["id"], branch["id"])
        resp = api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_success_data(api_client.get_ctr(ctr["id"], headers=make_officer_headers()))
        assert after["status"] == "VALIDATED"

    def test_rbac_examiner_cannot_post_transactions_but_can_read(self, api):
        """PRD §4 endpoint table: `POST /cash-transactions` — Authorized Role(s):
        `Teller`. `GET /ctrs` — Authorized Role(s): SystemAdmin, BranchManager,
        Teller, ComplianceAnalyst, BSAOfficer, Examiner.
        PRD §2.1: "A request whose authenticated role is not in the target
        endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_examiner_cannot_post_transactions_but_can_read
        """
        branch, customer = setup_branch_and_customer()
        resp = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "CASH_IN", "amount_cents": 100,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_examiner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        ok = api_client.list_ctrs(headers=make_examiner_headers(), params={})
        data = validate_success(ok)
        assert isinstance(data, list) and len(data) == 0

    def test_rbac_analyst_cannot_approve_exemption(self, api):
        """PRD §4 endpoint table: `POST /exemption-designations/{id}/approve` —
        Authorized Role(s): `BSAOfficer`.
        PRD §2.1: "A request whose authenticated role is not in the target
        endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_analyst_cannot_approve_exemption
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(legal_name="Rbac City", customer_type="GOVERNMENT_AGENCY",
                             account_opened_date="2020-01-01T00:00:00Z")
        ex = request_exemption(c1["id"], phase="PHASE_I", requester_id="officer-a")
        resp = api_client.approve_exemption(ex["id"], headers=make_analyst_headers("analyst-x"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert after["status"] == "PENDING_REVIEW"

    def test_rbac_manager_cannot_disposition_alert(self, api):
        """PRD §4 endpoint table: `POST /structuring-alerts/{id}/dismiss` —
        Authorized Role(s): `BSAOfficer`. `POST /structuring-alerts/{id}/begin-review`
        — Authorized Role(s): `ComplianceAnalyst`.
        PRD §2.1: "A request whose authenticated role is not in the target
        endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_manager_cannot_disposition_alert
        """
        branch, customer = setup_branch_and_customer()
        alert = alert_in_status(customer["id"], "UNDER_REVIEW", creator_id="officer-z")
        assert alert["status"] == "UNDER_REVIEW"
        resp = api_client.dismiss_alert(
            alert["id"], {"disposition_note": "nope"}, headers=make_manager_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestOptimisticConcurrency:
    def test_occ_customer_patch_stale_version(self, api):
        """PRD §2.9: "Updating a customer profile requires
        `expected_customer_version` matching the customer's current `version`.
        If another BranchManager has patched the customer since the caller last
        read it, the update is rejected."
        PRD §2.9: "in every case the field is non-optional and a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.1: "a profile patch that increments the customer's `version` by
        one".

        Design: Corner/cross_cutting_complexity_layers/occ_customer_patch_stale_version
        """
        from test_helpers import create_customer
        customer = create_customer(legal_name="Occ Olga")
        assert customer["version"] == 1
        # First writer succeeds and bumps version
        v2 = get_success_data(api_client.patch_customer(
            customer["id"], {"tin": "39-3939393", "expected_customer_version": 1},
            headers=make_manager_headers(),
        ))
        assert v2["version"] == 2
        # Replay with the stale observed version 1 is rejected
        resp = api_client.patch_customer(
            customer["id"],
            {"legal_name": "Occ Olga Renamed", "expected_customer_version": 1},
            headers=make_manager_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api_client.get_customer(customer["id"], headers=make_officer_headers()))
        assert after["legal_name"] == "Occ Olga"

    def test_occ_ctr_amend_stale_version(self, api):
        """PRD §2.9: "Creating a correction amendment against a CTR requires
        `expected_ctr_version` matching that CTR's current `version`. If the
        CTR's version has advanced since the filing officer last observed it—
        for instance because another officer has already superseded it—the
        amendment is rejected."
        PRD §2.9: "in every case the field is non-optional and a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_ctr_amend_stale_version
        """
        branch, customer = setup_branch_and_customer()
        filed = create_validated_ctr(customer["id"], branch["id"])
        filed = get_success_data(api_client.file_ctr(
            filed["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        ctr_v = filed["version"]
        # Stale version (one behind) rejected
        resp = api_client.amend_ctr(
            filed["id"],
            {"amendment_reason": "stale attempt", "expected_ctr_version": ctr_v - 1},
            headers=make_officer_headers("officer-y"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Fresh version succeeds; predecessor SUPERSEDED
        succ = get_success_data(api_client.amend_ctr(
            filed["id"],
            {"amendment_reason": "fresh attempt", "expected_ctr_version": ctr_v},
            headers=make_officer_headers("officer-y"),
        ))
        assert succ["id"]
        original = get_success_data(api_client.get_ctr(filed["id"], headers=make_officer_headers()))
        assert original["status"] == "SUPERSEDED"

    def test_occ_exemption_review_stale_version(self, api):
        """PRD §2.9: "Completing an annual review of an exemption designation
        requires `expected_exemption_version` matching the designation's
        current `version`, since the eligibility snapshot the reviewer relied
        on may no longer reflect the designation's state."
        PRD §2.9: "in every case the field is non-optional and a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_exemption_review_stale_version
        """
        set_clock("2026-01-02T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(legal_name="Occ City", customer_type="GOVERNMENT_AGENCY",
                             account_opened_date="2020-01-01T00:00:00Z")
        ex = create_active_phase_i_exemption(c1["id"], requester_id="officer-a",
                                             approver_id="officer-b")
        set_clock("2027-01-03T00:00:00Z")
        current = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert current["status"] == "REVIEW_DUE"
        resp = api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "PASS", "expected_exemption_version": current["version"] - 1},
            headers=make_officer_headers("officer-c"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        passed = get_success_data(api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "PASS", "expected_exemption_version": current["version"]},
            headers=make_officer_headers("officer-c"),
        ))
        assert passed["status"] == "ACTIVE"
