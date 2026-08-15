"""Trade verification gates: vendor diligence, segregation, windows, invalidation (PRD §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    CM,
    create_account,
    create_approved_vendor,
    create_delivered_trade,
    create_trade,
    create_vendor,
    get_purchased_lot_for_trade,
    get_success_data,
    make_compliance_manager_headers,
    make_trader_headers,
    set_clock,
    validate_error,
    validate_success,
    api_client,
)


class TestVerifyGatedByVendorDiligence:
    def test_verify_rejected_while_vendor_unvetted(self, api):
        """PRD §3.3: "The vendor must stand `APPROVED` at verification time (`ERR_VENDOR_NOT_APPROVED` otherwise)"

        Design: Difficulty/cross_entity_state_dependency/trade_verify_gated_by_vendor_diligence
        """
        acct = create_account(epa_registration_id="EPA-ACME-13")
        ven = create_vendor(acct["id"])  # UNVETTED
        trd = create_delivered_trade(acct["id"], ven["id"])
        resp = api.verify_trade(trd["id"], make_compliance_manager_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_APPROVED)

    def test_verify_succeeds_after_vendor_approved(self, api):
        """PRD §3.3: "Successful verification moves the transfer `DELIVERED` → `VERIFIED`, records `verified_by_user_id`, and makes the purchased lot retirement-eligible"

        Design: Difficulty/cross_entity_state_dependency/trade_verify_gated_by_vendor_diligence
        """
        acct = create_account(epa_registration_id="EPA-ACME-13B")
        ven = create_vendor(acct["id"])
        trd = create_delivered_trade(acct["id"], ven["id"])
        resp = api.verify_trade(trd["id"], make_compliance_manager_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_APPROVED)
        get_success_data(api.record_diligence(ven["id"], {"outcome": "APPROVED"}, CM))
        data = get_success_data(
            api.verify_trade(trd["id"], make_compliance_manager_headers("cm-1")),
        )
        assert data["transfer_status"] == "VERIFIED"
        assert data["verified_by_user_id"] == "cm-1"


class TestVerifyPrioritySafetyBeatsTemporal:
    def _setup_expired_window_unvetted(self, api, epa_id):
        acct = create_account(epa_registration_id=epa_id)
        ven = create_vendor(acct["id"], vendor_name="ShadyRIN Inc",
                            qap_audited=False)  # stays UNVETTED
        trd = create_delivered_trade(acct["id"], ven["id"],
                                     rin_qty=10, price_per_rin_cents=100)
        # Delivered at default clock 2026-08-01; advance 31 days past window.
        set_clock("2026-09-01T00:00:00Z")
        return trd

    def test_vendor_not_approved_fires_not_window_expired(self, api):
        """PRD §2.8: "Regulatory gates are evaluated after that: vendor approval (`ERR_VENDOR_NOT_APPROVED`), invalidated-RIN protection (`ERR_RIN_INVALIDATED`), the clean-attest gate (`ERR_ATTEST_NOT_CLEAN`), and category eligibility (`ERR_D_CODE_NOT_ELIGIBLE`). Uniqueness and overlap constraints follow (natural-key uniqueness violations via `ERR_INVALID_REQUEST`, plus `ERR_ENGAGEMENT_WINDOW_OVERLAP` and `ERR_PRICE_WINDOW_OVERLAP`), then the temporal gates (`ERR_INVALID_VINTAGE`, `ERR_DEADLINE_PASSED`, `ERR_VERIFICATION_WINDOW_EXPIRED`, `ERR_RETENTION_ACTIVE`)"

        Design: Difficulty/priority_pair_validation_conflict/verify_safety_beats_temporal_window
        """
        trd = self._setup_expired_window_unvetted(api, "EPA-ACME-10")
        resp = api.verify_trade(trd["id"], make_compliance_manager_headers("cm-1"))
        err = validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_APPROVED)
        assert err["error_id"] != ApiErrorId.ERR_VERIFICATION_WINDOW_EXPIRED

    def test_trade_remains_delivered_after_rejected_verify(self, api):
        """PRD §2.10: "And a delivered trade must be verified within thirty days of delivery: verification at exactly the thirtieth day remains inside the window, and any later attempt is rejected with `ERR_VERIFICATION_WINDOW_EXPIRED`."
        PRD §3.3: "The vendor must stand `APPROVED` at verification time (`ERR_VENDOR_NOT_APPROVED` otherwise)"

        Design: Difficulty/priority_pair_validation_conflict/verify_safety_beats_temporal_window
        """
        trd = self._setup_expired_window_unvetted(api, "EPA-ACME-10B")
        resp = api.verify_trade(trd["id"], make_compliance_manager_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_APPROVED)
        after = validate_success(api.get_rin_trade(trd["id"], CM))
        assert after["transfer_status"] == "DELIVERED"


class TestVerifyAfterInvalidation:
    def test_verify_on_invalidated_trade_rejected(self, api):
        """PRD §3.4: "Once a lot or trade stands `INVALIDATED`, later operations against it are guarded: separation against the lot, a second invalidation, or verification after invalidation are each rejected with `ERR_RIN_INVALIDATED`."

        Design: Corner/endpoints/verify_rejected_after_invalidation
        """
        acct = create_account(epa_registration_id="EPA-EP-4")
        ven = create_approved_vendor(acct["id"])
        trd = create_delivered_trade(acct["id"], ven["id"])
        get_success_data(api.invalidate_trade(trd["id"], CM))
        resp = api.verify_trade(trd["id"], make_compliance_manager_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_RIN_INVALIDATED)
        after = validate_success(api.get_rin_trade(trd["id"], CM))
        assert after["transfer_status"] == "INVALIDATED"


class TestSeparationOnInvalidatedLot:
    def test_separation_on_invalidated_lot_rejected(self, api):
        """PRD §3.2: "A lot that stands `INVALIDATED` refuses separation with `ERR_RIN_INVALIDATED`"
        PRD §2.8: "Regulatory gates are evaluated after that: vendor approval (`ERR_VENDOR_NOT_APPROVED`), invalidated-RIN protection (`ERR_RIN_INVALIDATED`), the clean-attest gate (`ERR_ATTEST_NOT_CLEAN`), and category eligibility (`ERR_D_CODE_NOT_ELIGIBLE`)."

        Design: Corner/errors/error_separation_on_invalidated_lot
        """
        acct = create_account(epa_registration_id="EPA-ERR-1")
        ven = create_approved_vendor(acct["id"])
        trd = create_delivered_trade(acct["id"], ven["id"],
                                     rin_qty=10, price_per_rin_cents=100)
        lot = get_purchased_lot_for_trade(trd["id"])
        get_success_data(api.invalidate_trade(trd["id"], CM))
        resp = api.create_separation(lot["id"], {"blended_gallons": 1}, CM)
        validate_error(resp, ApiErrorId.ERR_RIN_INVALIDATED)
        after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert after["status"] == "INVALIDATED"


class TestSegregationTradeCreatorCannotVerify:
    def test_creator_cannot_verify_own_trade(self, api):
        """PRD §3.3: "A `ComplianceManager` performs it, and the verifier must not be the trader who created the purchase — a verifier whose `X-User-ID` equals the trade's `created_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_trade_creator_cannot_verify
        """
        acct = create_account(epa_registration_id="EPA-RBAC-4")
        ven = create_approved_vendor(acct["id"], headers=make_trader_headers("tr-9"))
        h9 = make_trader_headers("tr-9")
        trd = create_delivered_trade(acct["id"], ven["id"], trader_headers=h9)
        # Same operator id (tr-9) holding ComplianceManager capacity attempts verify.
        resp = api.verify_trade(trd["id"], make_compliance_manager_headers("tr-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_different_verifier_succeeds(self, api):
        """PRD §3.3: "Successful verification moves the transfer `DELIVERED` → `VERIFIED`, records `verified_by_user_id`, and makes the purchased lot retirement-eligible"

        Design: Corner/rbac/segregation_trade_creator_cannot_verify
        """
        acct = create_account(epa_registration_id="EPA-RBAC-4B")
        ven = create_approved_vendor(acct["id"], headers=make_trader_headers("tr-9"))
        h9 = make_trader_headers("tr-9")
        trd = create_delivered_trade(acct["id"], ven["id"], trader_headers=h9)
        resp = api.verify_trade(trd["id"], make_compliance_manager_headers("tr-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        data = get_success_data(
            api.verify_trade(trd["id"], make_compliance_manager_headers("cm-2")),
        )
        assert data["transfer_status"] == "VERIFIED"
