"""Offering lifecycle gating, certificate funding side effects, committed-principal
aggregates, and list envelope (PRD §2.2, §2.3, §3.3, §3.4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_certificate, assert_offering,
    register_credit_union, register_cuso,
    create_draft_agreement, create_active_agreement, activate_agreement,
    create_draft_offering, create_open_offering,
    setup_pool, setup_pool_with_funded_cert, commit, approve_diligence,
    create_funded_certificate,
    make_cuso_officer_headers, make_originator_headers, make_buyer_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestOfferingCreationRequiresActiveAgreement:
    def test_create_offering_under_draft_agreement_rejected(self, api):
        """PRD §3.4: "An `OriginatorUser` lists a loan pool for participation by creating an offering under an `ACTIVE` servicing agreement — a request against an agreement in any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`, and the caller must own the agreement's `originator_id`."

        Design: Difficulty/cross_entity_state_dependency/offering_creation_requires_active_agreement
        """
        originator = register_credit_union(charter_number="CU-ORIG", cu_type="ORIGINATOR")
        cuso = register_cuso()
        agreement = create_draft_agreement(cuso["id"], originator["id"])
        res = api.create_offering(
            {"servicing_agreement_id": agreement["id"], "pool_name": "Pool A",
             "pool_principal_cents": 100_000_000, "min_share_pct": 0.01,
             "yield_rate_bps": 600, "open_at": "2026-08-01T00:00:00Z",
             "close_at": "2026-09-01T00:00:00Z"},
            make_originator_headers(originator["id"]))
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_create_offering_after_activation_succeeds_in_draft(self, api):
        """PRD §3.4: "Offerings begin in `DRAFT` and continuously expose `committed_principal_cents` — the sum of `committed_amount_cents` across certificates in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — and `remaining_principal_cents`, the pool principal minus that committed figure."
        PRD §3.4: "An `OriginatorUser` lists a loan pool for participation by creating an offering under an `ACTIVE` servicing agreement — a request against an agreement in any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`, and the caller must own the agreement's `originator_id`."

        Design: Difficulty/cross_entity_state_dependency/offering_creation_requires_active_agreement
        """
        originator = register_credit_union(charter_number="CU-ORIG", cu_type="ORIGINATOR")
        cuso = register_cuso()
        agreement = create_draft_agreement(cuso["id"], originator["id"])
        activate_agreement(agreement["id"], cuso["id"])
        offering = create_draft_offering(agreement["id"], originator["id"],
                                         pool_name="Pool A")
        assert_offering(offering)
        assert offering["status"] == "DRAFT"


class TestFundRequiresOpenOffering:
    def test_fund_against_closed_offering_rejected(self, api):
        """PRD §3.4: "Funding a `COMMITTED` certificate moves it to `ACTIVE`: `funded_amount_cents` and `outstanding_principal_cents` are both set to `committed_amount_cents`, `funded_at` is stamped from the clock (this instant later anchors repurchase accrual when no remittances exist), and funding is only possible while the offering is `OPEN` — a `SUSPENDED` or otherwise non-`OPEN` offering rejects funding with `ERR_OFFERING_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/fund_requires_open_offering
        """
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        cert = commit(ctx["offering"]["id"], buyer["id"], 10_000_000)
        approve_diligence(cert["id"], buyer["id"])
        validate_success(api.close_offering(ctx["offering"]["id"],
                                            make_originator_headers(ctx["originator"]["id"])), 200)

        res = api.fund_commitment(cert["id"], make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_OFFERING_NOT_OPEN)
        after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert after["status"] == "COMMITTED"

    def test_fund_while_open_succeeds(self, api):
        """PRD §3.4: "Funding a `COMMITTED` certificate moves it to `ACTIVE`: `funded_amount_cents` and `outstanding_principal_cents` are both set to `committed_amount_cents`, `funded_at` is stamped from the clock (this instant later anchors repurchase accrual when no remittances exist), and funding is only possible while the offering is `OPEN` — a `SUSPENDED` or otherwise non-`OPEN` offering rejects funding with `ERR_OFFERING_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/fund_requires_open_offering
        """
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        cert = commit(ctx["offering"]["id"], buyer["id"], 10_000_000)
        approve_diligence(cert["id"], buyer["id"])
        funded = validate_success(
            api.fund_commitment(cert["id"], make_buyer_headers(buyer["id"])), 200)
        assert funded["status"] == "ACTIVE"


class TestCommitRescindConservesCommittedPrincipal:
    def _commit_approve_rescind(self, api):
        """Offering OPEN (pool 100,000,000); buyer commits 20,000,000, approves
        diligence, then rescinds. Returns (ctx, buyer, rescinded certificate)."""
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        cert = commit(ctx["offering"]["id"], buyer["id"], 20_000_000)
        approve_diligence(cert["id"], buyer["id"])
        res = api.rescind_commitment(cert["id"], make_buyer_headers(buyer["id"]))
        return ctx, buyer, validate_success(res, 200)

    def test_offering_aggregates_restored_after_rescind(self, api):
        """PRD §3.4: "A buyer may also rescind an unfunded `COMMITTED` certificate, moving it to `RESCINDED` and recomputing the offering and buyer aggregates."
        PRD §3.4: "Offerings begin in `DRAFT` and continuously expose `committed_principal_cents` — the sum of `committed_amount_cents` across certificates in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — and `remaining_principal_cents`, the pool principal minus that committed figure."

        Design: Difficulty/compensating_invariant/commit_rescind_conserves_committed_principal
        """
        ctx, buyer, cert = self._commit_approve_rescind(api)
        assert cert["status"] == "RESCINDED"
        offering = validate_success(api.get_offering(ctx["offering"]["id"], ADMIN), 200)
        assert offering["committed_principal_cents"] == 0
        assert offering["remaining_principal_cents"] == 100_000_000

    def test_buyer_total_restored_after_rescind(self, api):
        """PRD §3.4: "A buyer may also rescind an unfunded `COMMITTED` certificate, moving it to `RESCINDED` and recomputing the offering and buyer aggregates."
        PRD §3.1: "Two figures are derived continuously: `net_worth_ratio`, the unrounded quotient of `net_worth_cents` over `total_assets_cents`, and `total_committed_principal_cents`, the sum of `committed_amount_cents` across the credit union's certificates currently in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION`."

        Design: Difficulty/compensating_invariant/commit_rescind_conserves_committed_principal
        """
        ctx, buyer, cert = self._commit_approve_rescind(api)
        buyer_after = validate_success(api.get_credit_union(buyer["id"], ADMIN), 200)
        assert buyer_after["total_committed_principal_cents"] == 0


class TestOfferingDerivedAggregates:
    def test_remaining_principal_derived_after_commit(self, api):
        """PRD §3.4: "Offerings begin in `DRAFT` and continuously expose `committed_principal_cents` — the sum of `committed_amount_cents` across certificates in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — and `remaining_principal_cents`, the pool principal minus that committed figure."
        PRD §3.4: "A successful commitment lands in `PENDING_DILIGENCE`, and the offering's `committed_principal_cents` and the buyer's `total_committed_principal_cents` are recomputed."

        Design: Corner/cross_cutting/offering_remaining_principal_derived_after_commit
        """
        ctx = setup_pool()
        commit(ctx["offering"]["id"], ctx["buyers"][0]["id"], 20_000_000)
        offering = validate_success(api.get_offering(ctx["offering"]["id"], ADMIN), 200)
        assert offering["committed_principal_cents"] == 20_000_000
        assert offering["remaining_principal_cents"] == 80_000_000

    def test_fund_response_carries_side_effects_immediately(self, api):
        """PRD §3.4: "Funding a `COMMITTED` certificate moves it to `ACTIVE`: `funded_amount_cents` and `outstanding_principal_cents` are both set to `committed_amount_cents`, `funded_at` is stamped from the clock (this instant later anchors repurchase accrual when no remittances exist), and funding is only possible while the offering is `OPEN` — a `SUSPENDED` or otherwise non-`OPEN` offering rejects funding with `ERR_OFFERING_NOT_OPEN`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/endpoints/fund_side_effects_visible_immediately
        """
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        cert = commit(ctx["offering"]["id"], buyer["id"], 10_000_000)
        approve_diligence(cert["id"], buyer["id"])
        funded = validate_success(
            api.fund_commitment(cert["id"], make_buyer_headers(buyer["id"])), 200)
        assert_certificate(funded)
        assert funded["status"] == "ACTIVE"
        assert funded["funded_amount_cents"] == 10_000_000
        assert funded["outstanding_principal_cents"] == 10_000_000

    def test_commitments_list_pagination_envelope(self, api, network_admin_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.3: "The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether additional pages remain."

        Design: Corner/endpoints/commitments_list_pagination_envelope
        """
        ctx = setup_pool(num_buyers=2)
        buyer1, buyer2 = ctx["buyers"]
        commit(ctx["offering"]["id"], buyer1["id"], 10_000_000)
        commit(ctx["offering"]["id"], buyer2["id"], 10_000_000)

        res = api.list_commitments(network_admin_headers,
                                   params={"offering_id": ctx["offering"]["id"], "limit": 1})
        data, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array"
        assert res.json()["meta"]["api_request_id"]
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestCertificateTerminalLockdown:
    def test_approve_diligence_on_active_certificate_rejected(self, api):
        """PRD §3.4: "Approving diligence moves the certificate from `PENDING_DILIGENCE` to `COMMITTED`, requires the caller to equal the certificate's `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), and stamps `diligence_decision_at`."
        PRD §2.7: "7. **State legality** — the target resource is in a state from which the requested transition exists, else `ERR_INVALID_STATE`. This check applies to all action endpoints."

        Design: Corner/state_machines/approve_diligence_on_active_certificate_rejected
        """
        ctx = setup_pool_with_funded_cert()
        buyer = ctx["buyers"][0]
        cert = ctx["certificate"]
        res = api.approve_diligence(cert["id"], make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert after["status"] == "ACTIVE"

    def test_rescind_declined_certificate_rejected(self, api):
        """PRD §3.4: "`DECLINED`, `RESCINDED`, and `REPURCHASED` are the certificate's terminal states, joined by `PAID_OFF` as a non-terminal resting state the certificate can leave again (§3.5)."
        PRD §3.4: "A buyer may also rescind an unfunded `COMMITTED` certificate, moving it to `RESCINDED` and recomputing the offering and buyer aggregates."

        Design: Corner/state_machines/rescind_declined_certificate_rejected
        """
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        cert = commit(ctx["offering"]["id"], buyer["id"], 10_000_000)
        validate_success(api.decline_commitment(cert["id"], make_buyer_headers(buyer["id"])), 200)
        res = api.rescind_commitment(cert["id"], make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
