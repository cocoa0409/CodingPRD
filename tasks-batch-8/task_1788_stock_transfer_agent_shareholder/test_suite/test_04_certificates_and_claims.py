"""Certificate form conversions, stop-transfer occupancy, lost-certificate
claims, and the dual-variant indemnity bond calculation."""
from test_helpers import (
    ApiErrorId,
    approve_claim,
    assert_issuer_conservation,
    get_claim,
    get_issuer,
    get_position,
    list_claims,
    make_supervisor_headers,
    post_bond,
    post_bond_payload,
    recover_certificate,
    setup_bond_posted_claim,
    setup_issuer_account_position,
    setup_lost_claim,
    setup_two_lost_certs_price_moved,
    validate_error,
    validate_success,
    withdraw_certificate,
    make_examiner_headers,
)


class TestBondVariantDivergence:
    def test_bond_fixed_penalty_prices_at_loss_report(self, api):
        """PRD §3.4: "Under `FIXED_PENALTY`, the reference price is the claim's
        `loss_report_price_cents`, frozen when the loss was first reported, so
        the bond is priced as of the loss report regardless of later market
        movement. In both variants the `bond_amount_cents` is the certificate's
        `share_quantity` multiplied by the variant's reference price,
        multiplied by two — the standard double-indemnity basis."
        PRD §3.4: "its `loss_report_price_cents` is frozen at the issuer's
        `current_market_price_cents` at the moment of the report"

        Design: Difficulty/dual_variant_calc/bond_open_vs_fixed_penalty_divergence
        """
        ctx = setup_two_lost_certs_price_moved()
        claim1 = post_bond(ctx["claim1"]["id"], "FIXED_PENALTY", 30000)

        assert claim1["loss_report_price_cents"] == 5000, (
            "the loss report froze the pre-move price"
        )
        assert claim1["bond_amount_cents"] == 1000000, (
            "100 shares x 5000 loss-report price x 2"
        )
        assert claim1["required_premium_cents"] == 30000, (
            "3% of 1000000, entirely under the tier-1 cap"
        )
        assert claim1["status"] == "BOND_POSTED"

    def test_bond_open_penalty_prices_at_post_time(self, api):
        """PRD §3.4: "Under `OPEN_PENALTY`, the reference price is the issuer's
        `current_market_price_cents` read at the moment the bond is posted, so
        a bond posted after a market move prices against the newer market."
        PRD §3.4: "The `required_premium_cents` is then tiered: 3 percent of
        the portion of the bond amount up to a cap of ten million cents (one
        hundred thousand dollars), plus 2 percent of any portion of the bond
        amount above that cap, with the total rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/bond_open_vs_fixed_penalty_divergence
        """
        ctx = setup_two_lost_certs_price_moved()
        claim1 = post_bond(ctx["claim1"]["id"], "FIXED_PENALTY", 30000)
        claim2 = post_bond(ctx["claim2"]["id"], "OPEN_PENALTY", 42000)

        assert claim2["bond_amount_cents"] == 1400000, (
            "100 shares x 7000 post-move price x 2"
        )
        assert claim2["required_premium_cents"] == 42000, "3% of 1400000"
        assert claim2["bond_amount_cents"] - claim1["bond_amount_cents"] == 400000, (
            "identical 100-share claims diverge only by variant x price timing"
        )


class TestStopTransferOccupancy:
    def test_second_report_lost_rejected(self, api):
        """PRD §3.4: "it must not already have an open claim: a certificate
        with a claim still in `FILED`, `BOND_POSTED`, or `APPROVED` status
        refuses a second report with `ERR_DUPLICATE_OPEN_CLAIM`, because the
        earlier stop-transfer occupancy is still in force."

        Design: Difficulty/resource_temporal_overlap/stop_order_open_occupancy_overlap
        """
        ctx = setup_lost_claim(cert_shares=50, book_entry_shares=100,
                               shares_outstanding=100)

        resp = api.report_lost(ctx["certificate"]["id"],
                               {"loss_date": "2026-08-11T00:00:00Z"},
                               make_examiner_headers("exam_2"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM)
        claims = list_claims(certificate_id=ctx["certificate"]["id"])
        assert len(claims) == 1, "the open occupancy admits exactly one claim"

    def test_stop_occupancy_persists_after_rejected_report(self, api):
        """PRD §3.4: "Reporting places the stop-transfer order: the certificate
        moves `ISSUED` → `LOST_REPORTED`, its `lost_reported_at` is stamped
        from the logical clock, and the stop remains open-ended until
        resolved."

        Design: Difficulty/resource_temporal_overlap/stop_order_open_occupancy_overlap
        """
        ctx = setup_lost_claim(cert_shares=50, book_entry_shares=100,
                               shares_outstanding=100)
        resp = api.report_lost(ctx["certificate"]["id"],
                               {"loss_date": "2026-08-11T00:00:00Z"},
                               make_examiner_headers("exam_2"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM)

        from test_helpers import get_certificate_for_account
        cert = get_certificate_for_account(ctx["account"]["id"],
                                           ctx["certificate"]["id"])
        assert cert["status"] == "LOST_REPORTED"
        assert cert["lost_reported_at"], "the stop order is still occupied"
        assert get_claim(ctx["claim"]["id"])["status"] == "FILED"


class TestShareConservation:
    def test_withdrawal_moves_form_not_count(self, api):
        """PRD §3.2: "On success the position's `book_entry_shares` decreases
        by the withdrawn quantity, its `certificated_shares` increases by the
        same amount, the position's `version` increments by one, and the
        issuer's totals are recomputed."
        PRD §2.10: "An issuer's `shares_outstanding` is the conservation anchor
        of the whole register"

        Design: Difficulty/compensating_invariant/share_conservation_withdrawal_redeposit
        """
        ctx = setup_issuer_account_position(shares_outstanding=500,
                                            book_entry_shares=500,
                                            holder_name="Vera Vault",
                                            state_code="CA")
        cert = withdraw_certificate(ctx["position"]["id"], 200)
        assert cert["status"] == "ISSUED"
        assert cert["share_quantity"] == 200

        pos = get_position(ctx["account"]["id"], ctx["issuer"]["id"])
        assert pos["book_entry_shares"] == 300
        assert pos["certificated_shares"] == 200
        assert pos["total_shares"] == 500, "form conversion conserves shares"
        issuer = get_issuer(ctx["issuer"]["id"])
        assert issuer["total_book_entry_shares"] == 300
        assert issuer["total_certificated_shares"] == 200
        assert_issuer_conservation(issuer)

    def test_redeposit_restores_book_entry(self, api):
        """PRD §3.2: "An examiner converting a certificate back to book-entry
        form requires the certificate to be `ISSUED`; the operation moves it
        `ISSUED` → `CANCELLED`, shifts its face quantity from the position's
        `certificated_shares` back into `book_entry_shares`, increments the
        position's `version`, and recomputes the issuer's totals."

        Design: Difficulty/compensating_invariant/share_conservation_withdrawal_redeposit
        """
        ctx = setup_issuer_account_position(shares_outstanding=500,
                                            book_entry_shares=500,
                                            holder_name="Vera Vault",
                                            state_code="CA")
        cert = withdraw_certificate(ctx["position"]["id"], 200)
        cancelled = validate_success(
            api.convert_to_drs(cert["id"], make_examiner_headers("exam_1")))
        assert cancelled["status"] == "CANCELLED"

        pos = get_position(ctx["account"]["id"], ctx["issuer"]["id"])
        assert pos["book_entry_shares"] == 500
        assert pos["certificated_shares"] == 0
        assert pos["total_shares"] == 500, (
            "withdrawal and redeposit compensate exactly"
        )
        issuer = get_issuer(ctx["issuer"]["id"])
        assert issuer["total_book_entry_shares"] == 500
        assert issuer["total_certificated_shares"] == 0
        assert issuer["shares_outstanding"] == 500


class TestCertificateRecovery:
    def test_certificate_recover_restores_issued_withdraws_claim(self, api):
        """PRD §3.4: "Recovery moves the certificate `LOST_REPORTED` → `ISSUED`
        and clears its `lost_reported_at`, ending the stop-transfer occupancy.
        Any claim still open against the certificate — one in `FILED` or
        `BOND_POSTED` status — moves to `WITHDRAWN` in the same operation, and
        its bond obligation is voided."

        Design: Corner/state_machines/certificate_recover_restores_issued_withdraws_claim
        """
        ctx = setup_lost_claim(cert_shares=30, book_entry_shares=100,
                               shares_outstanding=100)
        recovered = recover_certificate(ctx["certificate"]["id"])
        assert recovered["status"] == "ISSUED"
        assert recovered["lost_reported_at"] is None, "occupancy closed"

        claim = get_claim(ctx["claim"]["id"])
        assert claim["status"] == "WITHDRAWN", "cascade from the recovery"
        pos = get_position(ctx["account"]["id"], ctx["issuer"]["id"])
        assert pos["certificated_shares"] == 30, (
            "recovery changes form status, not the share count"
        )


class TestBondPremium:
    def test_bond_premium_tier_straddle(self, api):
        """PRD §3.4: "The `required_premium_cents` is then tiered: 3 percent of
        the portion of the bond amount up to a cap of ten million cents (one
        hundred thousand dollars), plus 2 percent of any portion of the bond
        amount above that cap, with the total rounded half-up to a whole cent."
        PRD §3.4: "In both variants the `bond_amount_cents` is the
        certificate's `share_quantity` multiplied by the variant's reference
        price, multiplied by two — the standard double-indemnity basis."

        Design: Corner/calculations/bond_premium_tier_straddle
        """
        ctx = setup_lost_claim(price_cents=60000, shares_outstanding=200,
                               book_entry_shares=200, cert_shares=100)
        claim = post_bond(ctx["claim"]["id"], "FIXED_PENALTY", 340000)

        assert claim["bond_amount_cents"] == 12000000, "100 x 60000 x 2"
        assert claim["required_premium_cents"] == 340000, (
            "10000000 x 3% + 2000000 x 2% — both tiers exercised"
        )
        assert claim["status"] == "BOND_POSTED", (
            "premium_paid_cents == required satisfies the inclusive floor"
        )

    def test_bond_premium_short_by_one_cent_rejected(self, api):
        """PRD §3.4: "Both computed figures are frozen onto the claim at this
        point, and the tendered premium must be at least the computed
        `required_premium_cents`; a tender even one cent short is refused with
        `ERR_BOND_PREMIUM_INSUFFICIENT`."

        Design: Corner/validations/bond_premium_short_by_one_cent_rejected
        """
        ctx = setup_lost_claim()  # price 5000, cert 100 -> required 30000
        resp = api.post_bond(ctx["claim"]["id"],
                             post_bond_payload("FIXED_PENALTY", 29999),
                             make_examiner_headers("exam_1"))
        validate_error(resp, ApiErrorId.ERR_BOND_PREMIUM_INSUFFICIENT)
        assert get_claim(ctx["claim"]["id"])["status"] == "FILED"


class TestClaimApprovalSegregation:
    def test_claim_approve_segregated_from_filing_examiner(self, api):
        """PRD §3.4: "Segregation of duties applies as on the transfer desk,
        with one asymmetry: when the claim was filed by an examiner, the
        approving supervisor's `X-User-ID` must differ from the claim's
        `filed_by_examiner_id`, and a violation is refused with
        `ERR_SEGREGATION_OF_DUTIES`"
        PRD §3.4: "its `filed_by_examiner_id` records the examiner's identifier
        when an examiner filed the report"

        Design: Corner/rbac/claim_approve_segregated_from_filing_examiner
        """
        ctx = setup_bond_posted_claim(examiner_id="exam_1")
        claim = get_claim(ctx["claim"]["id"])
        assert claim["filed_by_examiner_id"] == "exam_1"

        resp = api.approve_claim(claim["id"], make_supervisor_headers("exam_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = approve_claim(claim["id"], supervisor_id="sup_2")
        assert approved["status"] == "APPROVED"


class TestWithdrawalFunds:
    def test_withdrawal_exceeding_book_shares_rejected(self, api):
        """PRD §3.2: "The request is refused with `ERR_ZERO_SHARE_QUANTITY`
        when the `share_quantity` is below one, and with
        `ERR_INSUFFICIENT_SHARES` when it exceeds the position's
        `book_entry_shares`."

        Design: Corner/validations/withdrawal_exceeding_book_shares_rejected
        """
        ctx = setup_issuer_account_position(shares_outstanding=500,
                                            book_entry_shares=500,
                                            holder_name="Insuf Ivan")
        resp = api.withdraw_certificate(ctx["position"]["id"],
                                        {"share_quantity": 600},
                                        make_examiner_headers("exam_1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SHARES)
        pos = get_position(ctx["account"]["id"], ctx["issuer"]["id"])
        assert pos["book_entry_shares"] == 500
        assert pos["certificated_shares"] == 0
