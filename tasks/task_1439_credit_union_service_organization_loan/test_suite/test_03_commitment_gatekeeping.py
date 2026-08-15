"""Commitment gatekeeping: window, ownership, self-participation, duplicates,
minimum share, pool capacity, and concentration (PRD §2.7, §3.1, §3.4)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_certificate,
    register_credit_union, register_cuso, create_active_agreement,
    create_open_offering, setup_pool, commit, set_clock,
    make_buyer_headers, make_originator_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestCertificateCreation:
    def test_buyer_id_stamped_from_caller_header(self, api):
        """PRD §3.4: "the certificate's `buyer_id` is always set from the caller's `X-User-ID`, and any buyer value supplied in the payload is ignored."
        PRD §3.4: "A successful commitment lands in `PENDING_DILIGENCE`, and the offering's `committed_principal_cents` and the buyer's `total_committed_principal_cents` are recomputed."

        Design: Corner/entities/certificate_buyer_id_stamped_from_header
        """
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        cert = commit(ctx["offering"]["id"], buyer["id"], 10_000_000)
        assert_certificate(cert)
        assert cert["buyer_id"] == buyer["id"]
        assert cert["status"] == "PENDING_DILIGENCE"

    def test_buyer_cannot_touch_other_buyers_certificate(self, api):
        """PRD §2.1: "Where an endpoint acts on an existing resource owned by an entity-backed caller, a caller whose `X-User-ID` does not match the owning foreign key is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §3.4: "Approving diligence moves the certificate from `PENDING_DILIGENCE` to `COMMITTED`, requires the caller to equal the certificate's `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), and stamps `diligence_decision_at`."

        Design: Corner/rbac/buyer_cannot_touch_other_buyers_certificate
        """
        ctx = setup_pool(num_buyers=2)
        buyer_a, buyer_b = ctx["buyers"]
        cert = commit(ctx["offering"]["id"], buyer_a["id"], 10_000_000)
        res = api.approve_diligence(cert["id"], make_buyer_headers(buyer_b["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestCommitmentDomainConstraints:
    def test_self_participation_rejected(self, api):
        """PRD §3.4: "The buyer must not be the offering's originator, else `ERR_SELF_PARTICIPATION`."

        Design: Corner/validations/self_participation_rejected
        """
        dual = register_credit_union(charter_number="CU-DUAL", legal_name="Dual CU",
                                     cu_type="DUAL", total_assets_cents=50_000_000_000,
                                     net_worth_cents=5_000_000_000)
        cuso = register_cuso()
        agreement = create_active_agreement(cuso["id"], dual["id"])
        offering = create_open_offering(agreement["id"], dual["id"])
        res = api.create_commitment(
            {"offering_id": offering["id"], "committed_amount_cents": 10_000_000},
            make_buyer_headers(dual["id"]))
        validate_error(res, ApiErrorId.ERR_SELF_PARTICIPATION)

    def test_duplicate_commitment_rejected(self, api):
        """PRD §3.4: "The buyer may hold at most one non-terminal certificate in the offering, else `ERR_DUPLICATE_COMMITMENT`."

        Design: Corner/validations/duplicate_commitment_rejected
        """
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        commit(ctx["offering"]["id"], buyer["id"], 10_000_000)
        res = api.create_commitment(
            {"offering_id": ctx["offering"]["id"], "committed_amount_cents": 5_000_000},
            make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_COMMITMENT)

    def test_min_share_boundary_equality(self, api):
        """PRD §3.4: "The commitment must meet the minimum share — `committed_amount_cents` at least the product of `min_share_pct` and `pool_principal_cents` — else `ERR_MIN_SHARE_NOT_MET`."

        Design: Corner/validations/min_share_boundary_equality
        """
        ctx = setup_pool(num_buyers=2,
                         offering_overrides={"pool_principal_cents": 1_000_000_000,
                                             "min_share_pct": 0.01})
        offering = ctx["offering"]
        buyer1, buyer2 = ctx["buyers"]
        # Exactly the minimum (0.01 x 1,000,000,000 = 10,000,000) is allowed.
        ok = commit(offering["id"], buyer1["id"], 10_000_000)
        assert ok["status"] == "PENDING_DILIGENCE"
        # One cent below the minimum is rejected.
        res = api.create_commitment(
            {"offering_id": offering["id"], "committed_amount_cents": 9_999_999},
            make_buyer_headers(buyer2["id"]))
        validate_error(res, ApiErrorId.ERR_MIN_SHARE_NOT_MET)

    def test_pool_exhausted_rejected(self, api):
        """PRD §3.4: "And the commitment must fit the pool: `committed_amount_cents` no greater than the offering's `remaining_principal_cents`, else `ERR_POOL_EXHAUSTED`."

        Design: Corner/validations/pool_exhausted_rejected
        """
        ctx = setup_pool(num_buyers=2)
        offering = ctx["offering"]
        buyer1, buyer2 = ctx["buyers"]
        commit(offering["id"], buyer1["id"], 90_000_000)
        res = api.create_commitment(
            {"offering_id": offering["id"], "committed_amount_cents": 20_000_000},
            make_buyer_headers(buyer2["id"]))
        validate_error(res, ApiErrorId.ERR_POOL_EXHAUSTED)


class TestCommitmentWindowAndConcentration:
    def test_commitment_before_window_rejected(self, api):
        """PRD §3.4: "The commitment must fall within the inclusive window from `open_at` through `close_at`, else `ERR_OFFERING_WINDOW_CLOSED`."

        Design: Corner/validations/commitment_before_window_rejected
        """
        ctx = setup_pool(offering_overrides={"open_at": "2026-08-10T00:00:00Z",
                                             "close_at": "2026-12-01T00:00:00Z"})
        buyer = ctx["buyers"][0]
        # Clock is the startup default 2026-08-01T00:00:00Z, before open_at.
        res = api.create_commitment(
            {"offering_id": ctx["offering"]["id"], "committed_amount_cents": 10_000_000},
            make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_OFFERING_WINDOW_CLOSED)

    def test_concentration_cap_exceeded_rejected(self, api):
        """PRD §3.4: "A candidate exposure strictly above the cap is rejected with `ERR_CONCENTRATION_LIMIT_EXCEEDED`; exposure exactly equal to the cap is permitted."

        Design: Corner/validations/concentration_cap_exceeded_rejected
        """
        ctx = setup_pool(offering_overrides={"pool_principal_cents": 2_000_000_000,
                                             "min_share_pct": 0.01})
        buyer = ctx["buyers"][0]
        # cap = round_down(2,000,000,000 x 0.25) = 500,000,000; 500,000,001 exceeds it.
        res = api.create_commitment(
            {"offering_id": ctx["offering"]["id"], "committed_amount_cents": 500_000_001},
            make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_CONCENTRATION_LIMIT_EXCEEDED)

    def test_concentration_declined_certificate_excluded(self, api):
        """PRD §3.4: "The buyer's existing exposure to this originator is the sum of `committed_amount_cents` across every certificate where the buyer matches and the offering's agreement belongs to that originator, counting only certificates in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — `DECLINED`, `RESCINDED`, and `REPURCHASED` positions no longer count."
        PRD §3.4: "Declining moves it to `DECLINED`, stamps `diligence_decision_at` as well, and recomputes the offering and buyer aggregates, which from then on exclude the declined position."

        Design: Corner/calculations/concentration_declined_certificate_excluded
        """
        ctx = setup_pool(offering_overrides={"pool_principal_cents": 1_000_000_000,
                                             "min_share_pct": 0.01})
        buyer = ctx["buyers"][0]
        c1 = commit(ctx["offering"]["id"], buyer["id"], 490_000_000)
        validate_success(api.decline_commitment(c1["id"], make_buyer_headers(buyer["id"])), 200)

        # A fresh 10,000,000 commitment passes the 500,000,000 cap because the
        # DECLINED position no longer counts toward exposure.
        c2 = commit(ctx["offering"]["id"], buyer["id"], 10_000_000)
        assert c2["status"] == "PENDING_DILIGENCE"
        buyer_after = validate_success(api.get_credit_union(buyer["id"], ADMIN), 200)
        assert buyer_after["total_committed_principal_cents"] == 10_000_000


class TestReferentialBeatsTemporal:
    def _setup_open_offering_past_close(self, api, suspend_buyer: bool):
        """Offering OPEN with window [2026-08-01, 2026-09-01]; sweep NOT run so the
        offering remains OPEN; clock moved to 2026-09-02 (past close_at)."""
        ctx = setup_pool(offering_overrides={"open_at": "2026-08-01T00:00:00Z",
                                             "close_at": "2026-09-01T00:00:00Z"})
        buyer = ctx["buyers"][0]
        if suspend_buyer:
            validate_success(api.suspend_credit_union(buyer["id"], ADMIN), 200)
        set_clock("2026-09-02T00:00:00Z")
        return ctx, buyer

    def test_suspended_buyer_past_close_gets_credit_union_not_active(self, api):
        """PRD §2.7: "The server evaluates request validation in a fixed priority order, so that when several checks would fail, the caller always sees the same error."
        PRD §3.1: "Suspension is a gate, not a cascade: while a credit union is `SUSPENDED`, new commitments by that buyer and the opening of offerings by that originator are rejected with `ERR_CREDIT_UNION_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_commitment
        """
        ctx, buyer = self._setup_open_offering_past_close(api, suspend_buyer=True)
        res = api.create_commitment(
            {"offering_id": ctx["offering"]["id"], "committed_amount_cents": 10_000_000},
            make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_CREDIT_UNION_NOT_ACTIVE)

    def test_active_buyer_past_close_gets_window_closed(self, api):
        """PRD §3.4: "The commitment must fall within the inclusive window from `open_at` through `close_at`, else `ERR_OFFERING_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_commitment
        """
        ctx, buyer = self._setup_open_offering_past_close(api, suspend_buyer=False)
        res = api.create_commitment(
            {"offering_id": ctx["offering"]["id"], "committed_amount_cents": 10_000_000},
            make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_OFFERING_WINDOW_CLOSED)

    def test_suspended_buyer_within_window_gets_credit_union_not_active(self, api):
        """PRD §3.1: "Suspension is a gate, not a cascade: while a credit union is `SUSPENDED`, new commitments by that buyer and the opening of offerings by that originator are rejected with `ERR_CREDIT_UNION_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_commitment
        """
        ctx = setup_pool()
        buyer = ctx["buyers"][0]
        validate_success(api.suspend_credit_union(buyer["id"], ADMIN), 200)
        res = api.create_commitment(
            {"offering_id": ctx["offering"]["id"], "committed_amount_cents": 10_000_000},
            make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_CREDIT_UNION_NOT_ACTIVE)
