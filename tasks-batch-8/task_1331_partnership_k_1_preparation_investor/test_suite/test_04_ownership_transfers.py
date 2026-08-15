"""Ownership transfers: confirm battery, closed-window overlap, foreign cap,
settle timing, and the four-hop settle cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, CANONICAL_FEE_FUND, CANONICAL_TOTALS,
    create_fund, create_partner, create_tax_year, get_tax_year,
    create_transfer, confirm_transfer, create_and_confirm_transfer,
    get_partner, get_k1_package, get_allocation_run,
    setup_k1_generated, walk_k1_to_delivered, set_clock,
    create_transfer_payload,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]


def _two_partner_fund(api, fund_overrides=None):
    """T1 (US_INDIVIDUAL, CA, 6000bps) + T2 (US_ENTITY, DE, 4000bps) + 2025 year."""
    fund = create_fund(fund_overrides)
    t1 = create_partner(
        fund["id"], legal_name="T1", partner_type="US_INDIVIDUAL",
        residency_state="CA", ownership_pct_bps=6000,
    )
    t2 = create_partner(
        fund["id"], legal_name="T2", partner_type="US_ENTITY",
        residency_state="DE", ownership_pct_bps=4000,
    )
    ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=0)
    return fund, t1, t2, ty


class TestConfirmRequiresActivePartners:
    def _scenario(self, api):
        fund, t1, t2, ty = _two_partner_fund(api)
        validate_success(api.withdraw_partner(t2["id"], ADMIN), 200)
        transfer = create_transfer(
            fund["id"], t1["id"], t2["id"],
            pct_bps=1000, effective_date="2025-03-01", settlement_date="2025-03-05",
        )
        return transfer

    def test_transfer_confirm_rejected_when_transferee_withdrawn(self, api):
        """PRD §3.3: "Both partners must exist in the same fund and be
        distinct, and both must be `ACTIVE`, else
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/transfer_confirm_requires_active_partners
        """
        transfer = self._scenario(api)
        resp = api.confirm_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_transfer_confirm_rejection_leaves_proposed(self, api):
        """PRD §3.3: "A proposal begins `PROPOSED` with
        `transferred_capital_cents` still null."
        PRD §3.3: "Both partners must exist in the same fund and be distinct,
        and both must be `ACTIVE`, else `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/transfer_confirm_requires_active_partners
        """
        transfer = self._scenario(api)
        validate_error(api.confirm_transfer(transfer["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_transfer(transfer["id"], ADMIN), 200)
        assert after["status"] == "PROPOSED", f"rejected confirm must leave PROPOSED: {after['status']}"


class TestTransferClosedWindowOverlap:
    def _scenario(self, api):
        fund, t1, t2, ty = _two_partner_fund(api)
        tr1 = create_and_confirm_transfer(
            fund["id"], t1["id"], t2["id"],
            pct_bps=1000, effective_date="2025-03-01", settlement_date="2025-03-10",
        )
        tr2 = create_transfer(
            fund["id"], t1["id"], t2["id"],
            pct_bps=1000, effective_date="2025-03-10", settlement_date="2025-03-20",
        )
        return tr1, tr2

    def test_shared_endpoint_date_counts_as_overlap(self, api):
        """PRD §3.3: "The closed interval running from `effective_date` through
        `settlement_date` must not intersect any other `PROPOSED`, `CONFIRMED`,
        or `SETTLED` transfer of the same transferor, and sharing an endpoint
        date counts as overlap, else `ERR_TRANSFER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/transfer_closed_interval_shared_endpoint
        """
        tr1, tr2 = self._scenario(api)
        assert tr1["status"] == "CONFIRMED"
        resp = api.confirm_transfer(tr2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)

    def test_overlap_rejection_leaves_second_transfer_proposed(self, api):
        """PRD §3.3: "The closed interval running from `effective_date` through
        `settlement_date` must not intersect any other `PROPOSED`, `CONFIRMED`,
        or `SETTLED` transfer of the same transferor, and sharing an endpoint
        date counts as overlap, else `ERR_TRANSFER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/transfer_closed_interval_shared_endpoint
        """
        tr1, tr2 = self._scenario(api)
        validate_error(api.confirm_transfer(tr2["id"], ADMIN), ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)
        after = validate_success(api.get_transfer(tr2["id"], ADMIN), 200)
        assert after["status"] == "PROPOSED"


class TestTransferSettleFourHopCascade:
    def _scenario(self, api):
        """Canonical GP/LP1/LP2 fund, 2025 APPROVED with K-1s, GP's K-1 prep
        APPROVED, and a CONFIRMED LP1 -> LP3 transfer of 2000bps."""
        scenario = setup_k1_generated(
            fund_overrides=CANONICAL_FEE_FUND,
            tax_year_overrides=dict(CANONICAL_TOTALS),
            contributions=[
                ("gp1", 10000000, "2025-01-01"),
                ("lp1", 60000000, "2025-01-01"),
                ("lp2", 30000000, "2025-01-01"),
            ],
        )
        k1_gp = scenario["k1_packages"][0]
        assert k1_gp["partner_id"] == scenario["partners"]["gp1"]["id"]
        # prep GENERATED -> REVIEWED -> APPROVED (submitter != approver)
        from test_helpers import make_tax_preparer_headers, make_tax_reviewer_headers, PREPARER_USER_ID, REVIEWER_USER_ID
        validate_success(api.submit_k1_review(k1_gp["id"], make_tax_preparer_headers(PREPARER_USER_ID)), 200)
        validate_success(api.approve_k1(k1_gp["id"], make_tax_reviewer_headers(REVIEWER_USER_ID)), 200)
        lp3 = create_partner(
            scenario["fund"]["id"], legal_name="LP3", partner_type="US_INDIVIDUAL",
            residency_state="NY", ownership_pct_bps=1, capital_commitment_cents=1,
        )
        transfer = create_and_confirm_transfer(
            scenario["fund"]["id"], scenario["partners"]["lp1"]["id"], lp3["id"],
            pct_bps=2000, effective_date="2025-06-01", settlement_date="2025-06-10",
        )
        return scenario, k1_gp, lp3, transfer

    def test_settle_moves_capital_and_ownership(self, api):
        """PRD §3.3: "At settlement the system computes
        `transferred_capital_cents`: the transferor’s book capital balance as
        of the `effective_date`, multiplied by `pct_bps` and divided by the
        transferor’s ownership share in basis points that was in effect during
        the proration segment immediately before the `effective_date`, rounded
        half-up to integer cents."
        PRD §3.3: "First, a `TRANSFER_OUT` capital account event is created on
        the transferor and a `TRANSFER_IN` event on the transferee, each for
        `transferred_capital_cents` with the transfer’s `effective_date`.
        Second, because those events enter the replay stream, both partners’
        `capital_account_balance_cents`, `tax_basis_cents`, and
        `current_ownership_pct_bps` are recomputed."

        Design: Difficulty/transitive_cascade/transfer_settle_four_hop_cascade
        """
        scenario, k1_gp, lp3, transfer = self._scenario(api)
        lp1 = scenario["partners"]["lp1"]
        resp = api.settle_transfer(transfer["id"], ADMIN)
        settled = validate_success(resp, 200)
        assert settled["status"] == "SETTLED"
        # LP1 book balance at 2025-06-01 is 60000000 (the lock-posted
        # ALLOCATION_SHARE is dated 2025-12-31): 60000000 x 2000/6000.
        assert settled["transferred_capital_cents"] == 20000000
        lp1_after = get_partner(lp1["id"])
        # 60000000 + 19558667 ALLOCATION_SHARE - 20000000 TRANSFER_OUT
        assert lp1_after["capital_account_balance_cents"] == 59558667, (
            f"hop 2 transferor balance: {lp1_after['capital_account_balance_cents']}"
        )
        assert lp1_after["current_ownership_pct_bps"] == 4000
        lp3_after = get_partner(lp3["id"])
        assert lp3_after["capital_account_balance_cents"] == 20000000
        assert lp3_after["current_ownership_pct_bps"] == 2001

    def test_settle_stales_run_and_reverts_approved_k1(self, api):
        """PRD §3.3: "Third, every `LOCKED` allocation run whose tax year
        contains the `effective_date` transitions to `STALE`, since the
        recompute invalidated its proration inputs. Fourth, every K-1 package
        of such a tax year whose preparation is `REVIEWED` or `APPROVED`
        reverts to `GENERATED`."

        Design: Difficulty/transitive_cascade/transfer_settle_four_hop_cascade
        """
        scenario, k1_gp, lp3, transfer = self._scenario(api)
        validate_success(api.settle_transfer(transfer["id"], ADMIN), 200)
        run_after = get_allocation_run(scenario["run"]["id"])
        assert run_after["status"] == "STALE", f"hop 3 run must go STALE: {run_after['status']}"
        k1_after = get_k1_package(k1_gp["id"])
        assert k1_after["prep_status"] == "GENERATED", (
            f"hop 4 APPROVED package must revert to GENERATED: {k1_after['prep_status']}"
        )


class TestTransferValidation:
    def test_same_partner_transfer_rejected(self, api):
        """PRD §3.3: "The two partners must belong to the stated fund —
        cross-fund references are rejected with `ERR_CROSS_FUND_REFERENCE` —
        and must be distinct, else `ERR_SAME_PARTNER_TRANSFER`."

        Design: Corner/validations/same_partner_transfer_rejected
        """
        fund = create_fund()
        p = create_partner(fund["id"], legal_name="P")
        resp = api.create_transfer(
            create_transfer_payload(fund["id"], p["id"], p["id"], pct_bps=100),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_PARTNER_TRANSFER)

    def test_insufficient_ownership_rejected(self, api):
        """PRD §3.3: "Finally, `pct_bps` must not exceed the transferor’s
        `current_ownership_pct_bps` — transferring the entire current share is
        permitted — else `ERR_INSUFFICIENT_OWNERSHIP`."

        Design: Corner/errors/insufficient_ownership_rejected
        """
        fund, t1, t2, ty = _two_partner_fund(api)
        transfer = create_transfer(
            fund["id"], t1["id"], t2["id"],
            pct_bps=6001, effective_date="2025-03-01", settlement_date="2025-03-05",
        )
        resp = api.confirm_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_OWNERSHIP)

    def test_foreign_cap_exactly_at_cap_passes(self, api):
        """PRD §3.3: "The projected aggregate foreign-partner ownership share
        after the transfer must not exceed the fund’s
        `foreign_ownership_cap_pct_bps` — because the cap is inclusive, a
        projection landing exactly on it passes — and an excess is rejected
        with `ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED`."

        Design: Corner/validations/foreign_cap_exactly_at_cap_passes
        """
        fund = create_fund({"foreign_ownership_cap_pct_bps": 5000})
        p_us = create_partner(
            fund["id"], legal_name="P_US", partner_type="US_INDIVIDUAL",
            residency_state="CA", ownership_pct_bps=6000,
        )
        p_fr = create_partner(
            fund["id"], legal_name="P_FR", partner_type="FOREIGN_INDIVIDUAL",
            residency_state="XX", ownership_pct_bps=4000,
        )
        transfer = create_transfer(
            fund["id"], p_us["id"], p_fr["id"],
            pct_bps=1000, effective_date="2025-03-01", settlement_date="2025-03-05",
        )
        resp = api.confirm_transfer(transfer["id"], ADMIN)
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED", "foreign share exactly at the 50% cap must pass"

    def test_transfer_settle_before_settlement_date_rejected(self, api):
        """PRD §3.3: "Settlement moves a `CONFIRMED` transfer to `SETTLED` and
        is allowed only once the current clock date has reached the
        `settlement_date`; settling earlier is rejected with
        `ERR_TAX_YEAR_WINDOW_CLOSED`."

        Design: Corner/validations/transfer_settle_before_settlement_date_rejected
        """
        fund, t1, t2, ty = _two_partner_fund(api)
        transfer = create_and_confirm_transfer(
            fund["id"], t1["id"], t2["id"],
            pct_bps=1000, effective_date="2025-06-01", settlement_date="2025-06-10",
        )
        set_clock("2025-06-01T00:00:00Z")
        resp = api.settle_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_TAX_YEAR_WINDOW_CLOSED)
        after = validate_success(api.get_transfer(transfer["id"], ADMIN), 200)
        assert after["status"] == "CONFIRMED"


class TestTransferConfirmSafetyBeatsTemporal:
    def _scenario(self, api):
        """Foreign-cap-5000 fund with both partners' K-1s delivered (tax year
        COMPLETED), plus a PROPOSED P_US -> P_FR transfer of 2000bps whose
        effective date lies inside the COMPLETED year."""
        fund = create_fund({"foreign_ownership_cap_pct_bps": 5000})
        p_us = create_partner(
            fund["id"], legal_name="P_US", partner_type="US_INDIVIDUAL",
            residency_state="CA", ownership_pct_bps=6000,
        )
        p_fr = create_partner(
            fund["id"], legal_name="P_FR", partner_type="FOREIGN_INDIVIDUAL",
            residency_state="XX", ownership_pct_bps=4000,
        )
        # build the approved year + generation set on this fund explicitly
        from test_helpers import (
            close_books, create_and_lock_final_run, submit_tax_year_review,
            approve_tax_year, generate_k1_packages,
        )
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        close_books(ty["id"])
        create_and_lock_final_run(ty["id"])
        submit_tax_year_review(ty["id"])
        approve_tax_year(ty["id"])
        packages = generate_k1_packages(ty["id"])
        for package in packages:
            walk_k1_to_delivered(package["id"], "PORTAL")
        assert get_tax_year(ty["id"])["status"] == "COMPLETED"
        transfer = create_transfer(
            fund["id"], p_us["id"], p_fr["id"],
            pct_bps=2000, effective_date="2025-06-01", settlement_date="2025-06-05",
        )
        return transfer

    def test_confirm_reports_foreign_cap_not_window_closed(self, api):
        """PRD §2.8: "Every request is evaluated against a fixed validation
        pipeline and is rejected with the first failing check in the order
        below; later checks never mask earlier ones."
        PRD §2.8: "Foreign-ownership projection — a transfer confirmation’s
        projected aggregate foreign ownership must remain within the fund cap,
        else `ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED`."
        PRD §2.8: "Tax-year window rules — transfer confirmation with an
        `effective_date` in a `COMPLETED` tax year, capital events with an
        `effective_date` in a `COMPLETED` tax year, transfer settlement
        attempted before its `settlement_date`, special-allocation approval
        after the year has been `ALLOCATED`, and `FINAL` run computation, run
        locking, or composite filing while the year is `OPEN` or `COMPLETED`
        are rejected with `ERR_TAX_YEAR_WINDOW_CLOSED` or
        `ERR_TAX_YEAR_NOT_BOOKS_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/transfer_confirm_safety_beats_temporal
        """
        transfer = self._scenario(api)
        resp = api.confirm_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED)

    def test_confirm_rejection_leaves_transfer_proposed(self, api):
        """PRD §3.3: "A proposal begins `PROPOSED` with
        `transferred_capital_cents` still null."
        PRD §2.8: "Foreign-ownership projection — a transfer confirmation’s
        projected aggregate foreign ownership must remain within the fund cap,
        else `ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/transfer_confirm_safety_beats_temporal
        """
        transfer = self._scenario(api)
        validate_error(api.confirm_transfer(transfer["id"], ADMIN), ApiErrorId.ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED)
        after = validate_success(api.get_transfer(transfer["id"], ADMIN), 200)
        assert after["status"] == "PROPOSED"


class TestTransferListing:
    def test_filtered_list_reverse_reaches_children(self, api):
        """PRD §3.3: "The transfer list may be filtered by `fund_id`,
        `transferor_partner_id`, `transferee_partner_id`, and `status`."

        Design: Corner/endpoints/filtered_list_reverse_reaches_children
        """
        fund = create_fund()
        t1 = create_partner(fund["id"], legal_name="T1", ownership_pct_bps=5000, residency_state="CA")
        t2 = create_partner(
            fund["id"], legal_name="T2", partner_type="US_ENTITY",
            ownership_pct_bps=3000, residency_state="DE",
        )
        t3 = create_partner(fund["id"], legal_name="T3", ownership_pct_bps=2000, residency_state="WA")
        create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=0)
        tr1 = create_transfer(
            fund["id"], t1["id"], t2["id"],
            pct_bps=100, effective_date="2025-03-01", settlement_date="2025-03-05",
        )
        tr3 = create_transfer(
            fund["id"], t3["id"], t2["id"],
            pct_bps=100, effective_date="2025-04-01", settlement_date="2025-04-05",
        )
        data, meta = validate_paginated(
            api.list_transfers(ADMIN, params={"transferor_partner_id": t1["id"]})
        )
        assert meta["total_count"] == 1, f"exactly one transfer for T1: {meta['total_count']}"
        assert data[0]["id"] == tr1["id"]
        assert all(t["id"] != tr3["id"] for t in data), "T3's transfer must be excluded"
