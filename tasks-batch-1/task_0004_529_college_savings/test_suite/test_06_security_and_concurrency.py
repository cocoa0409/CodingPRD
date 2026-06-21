"""Security and concurrency tests: RBAC and OCC stale-version detection."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    setup_donor_beneficiary_account,
    create_and_post_contribution,
    create_draft_withdrawal,
    submit_withdrawal,
    create_donor,
    make_account_owner_headers,
    make_compliance_headers,
    make_custodian_headers,
    make_anonymous_headers,
    create_donor_payload,
    approve_withdrawal_payload,
)


# ---------------------------------------------------------------------------
# Corner/rbac
# ---------------------------------------------------------------------------

class TestRoleBasedAccessControl:
    def test_missing_x_user_role_header_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two headers identifying the caller:
        X-User-ID and X-User-Role. The role header is matched against a closed enumeration of
        four roles, spelled exactly as follows: AccountOwner, CustodianAgent,
        ComplianceOfficer, and SystemTaxAuthority. A request that omits the role header, or
        supplies a value outside the closed set, is rejected with ERR_UNAUTHENTICATED (HTTP
        401)."

        Design: Corner/rbac/missing_x_user_role_header_unauthenticated
        """
        resp = api.create_donor(
            create_donor_payload(
                full_name="X", state_code="CA", federal_tax_id_last4="1111", email="unauth@x.com"
            ),
            make_anonymous_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    def test_account_owner_cannot_create_donor(self, api):
        """PRD §2.1: "A request whose role is recognized but is not on the endpoint's allow-list
        is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/account_owner_cannot_create_donor
        """
        donor = create_donor(email="dxo@x.com")
        # An existing donor acting as AccountOwner attempts /donors (CustodianAgent-only).
        resp = api.create_donor(
            create_donor_payload(
                full_name="Y", state_code="CA", federal_tax_id_last4="2222", email="y@x.com"
            ),
            make_account_owner_headers(donor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    def test_account_owner_cannot_approve_own_withdrawal(self, api):
        """PRD §2.1: "A request whose role is recognized but is not on the endpoint's allow-list
        is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/account_owner_cannot_approve_own_withdrawal
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="dao@x.com")
        posted = create_and_post_contribution(account["id"], 100_000)
        a_v = posted["version"]
        w = create_draft_withdrawal(account["id"], donor["id"], 30_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        # AccountOwner attempts /approve (ComplianceOfficer-only).
        resp = api.approve_withdrawal(
            w["id"], approve_withdrawal_payload(a_v), make_account_owner_headers(donor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers — OCC
# ---------------------------------------------------------------------------

class TestOptimisticConcurrency:
    def test_occ_stale_account_version_on_withdrawal_approve(self, api):
        """PRD §2.7: "The first such operation is approving a Withdrawal. The request body must
        include expected_account_version carrying the client's last observed version of the
        target Account. If expected_account_version does not match the Account's current
        version at the moment the approve is processed, the request is rejected with
        ERR_STALE_ACCOUNT_VERSION (HTTP 412); this protects the basis/earnings split, the K-12
        excess computation, and the federal-penalty computation from being pinned against an
        account snapshot that has since shifted because of a second posted contribution, a
        disbursement of another withdrawal, or any other intervening account-version bump."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_withdrawal_approve
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="dsv@x.com")
        posted = create_and_post_contribution(account["id"], 200_000)
        a_v_observed = posted["version"]
        w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        # Bump account version via restrict + release.
        api.restrict_account(account["id"], make_compliance_headers())
        api.release_account(account["id"], make_compliance_headers())
        # Approve with stale expected_account_version.
        resp = api.approve_withdrawal(
            w["id"], approve_withdrawal_payload(a_v_observed), make_compliance_headers()
        )
        validate_error(
            resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value, expected_status=412
        )
        cur = api.get_withdrawal(w["id"], make_account_owner_headers(donor["id"])).json()["data"]
        assert cur["status"] == "SUBMITTED"
