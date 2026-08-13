"""Allocation engine: waterfall tiers, run kinds, proration, supersession,
optimistic concurrency, and role gating on run endpoints."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, CANONICAL_FEE_FUND, CANONICAL_TOTALS,
    CANONICAL_PARTNERS, PREPARER_USER_ID, REVIEWER_USER_ID,
    make_tax_preparer_headers, make_tax_reviewer_headers,
    make_investor_services_rep_headers,
    create_fund, create_partner, create_tax_year, close_books, get_tax_year,
    post_capital_event, create_allocation_run, create_and_lock_final_run,
    create_allocation_run_payload, setup_fund_with_partners,
    create_and_confirm_transfer, settle_transfer, create_partner_payload,
    create_and_approve_special_allocation, set_clock,
    find_line, get_allocation_run, assert_allocation_run, lock_run,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]
REVIEWER = TEST_USERS["tax_reviewer_headers"]
REP = TEST_USERS["investor_services_rep_headers"]


def _run_lines(api, run_id):
    data, meta = validate_paginated(api.list_run_lines(run_id, PREPARER, params={"limit": 100}))
    return data


class TestWaterfallTiers:
    def _scenario(self, api):
        """Canonical fund (fee 100bps with the discount applying, hurdle 800,
        catchup 2000, carry 2000) with GP1/LP1/LP2 at 1000/6000/3000 bps and
        2025-01-01 contributions 10000000/60000000/30000000."""
        fund, partners = setup_fund_with_partners(fund_overrides=CANONICAL_FEE_FUND)
        ty = create_tax_year(fund["id"], year=2025, **CANONICAL_TOTALS)
        for key, amount in (("gp1", 10000000), ("lp1", 60000000), ("lp2", 30000000)):
            post_capital_event(partners[key]["id"], ty["id"], "CONTRIBUTION", amount, "2025-01-01")
        close_books(ty["id"])
        run = create_allocation_run(ty["id"], run_kind="FINAL")
        return partners, run

    def test_capital_gain_waterfall_tier_amounts(self, api):
        """PRD §3.4: "The preferred tier computes each `LIMITED` partner’s
        preferred need as the fund’s `waterfall_hurdle_rate_bps` multiplied by
        the partner’s beginning capital and divided by ten thousand; the
        preferred pool is the smaller of the capital-gain total and the sum of
        all preferred needs, and if the pool falls short, each `LIMITED`
        partner is scaled down pro rata — their need multiplied by the pool and
        divided by the sum of needs, rounded."
        PRD §3.4: "The catch-up tier caps itself at the preferred pool
        multiplied by `waterfall_catchup_bps` and divided by ten thousand,
        rounded half-up; the catch-up pool is the smaller of the capital-gain
        total remaining after the preferred pool and that cap, and it goes
        entirely to `GENERAL` partners split by their renormalized weights."
        PRD §3.4: "The residual tier takes whatever capital gain remains after
        the preferred and catch-up pools: the limited-partner pool is that
        remainder multiplied by ten thousand minus `waterfall_carry_bps` and
        divided by ten thousand, rounded half-up, split over `LIMITED` partners
        by renormalized weight, and the general-partner pool is the remainder
        minus the limited-partner pool, split over `GENERAL` partners by
        renormalized weight."

        Design: Difficulty/combinatorial_formula/waterfall_tier_allocation_capital_gain
        """
        partners, run = self._scenario(api)
        lines = _run_lines(api, run["id"])
        # preferred 7200000, catchup 1440000, residual 11360000 -> LP 9088000 / GP 2272000
        cg_gp = find_line(lines, partners["gp1"]["id"], "CAPITAL_GAIN")
        cg_lp1 = find_line(lines, partners["lp1"]["id"], "CAPITAL_GAIN")
        cg_lp2 = find_line(lines, partners["lp2"]["id"], "CAPITAL_GAIN")
        assert cg_gp["amount_cents"] == 3712000, f"GP catchup+residual: {cg_gp['amount_cents']}"
        assert cg_lp1["amount_cents"] == 10858667, f"LP1 preferred+residual: {cg_lp1['amount_cents']}"
        assert cg_lp2["amount_cents"] == 5429333, f"LP2 preferred+residual: {cg_lp2['amount_cents']}"
        total = sum(l["amount_cents"] for l in lines if l["category"] == "CAPITAL_GAIN")
        assert total == 20000000, f"capital-gain lines must conserve the total: {total}"

    def test_ordinary_pro_rata_and_run_totals(self, api):
        """PRD §3.4: "In the pro-rata tier, the remaining pool is split across
        the non-special partners by their proration weights renormalized over
        that group."
        PRD §3.4: "For every category, the run’s allocation lines sum to
        exactly the category total, so no cents drift."
        PRD §3.4: "The run records the category totals it actually allocated as
        `ordinary_total_cents`, `capital_gain_total_cents`, and
        `interest_total_cents`."

        Design: Difficulty/combinatorial_formula/waterfall_tier_allocation_capital_gain
        """
        partners, run = self._scenario(api)
        run_data = get_allocation_run(run["id"])
        assert run_data["ordinary_total_cents"] == 9500000
        assert run_data["capital_gain_total_cents"] == 20000000
        assert run_data["interest_total_cents"] == 5000000
        lines = _run_lines(api, run["id"])
        assert find_line(lines, partners["gp1"]["id"], "ORDINARY")["amount_cents"] == 950000
        assert find_line(lines, partners["lp1"]["id"], "ORDINARY")["amount_cents"] == 5700000
        assert find_line(lines, partners["lp2"]["id"], "ORDINARY")["amount_cents"] == 2850000
        ordinary_sum = sum(l["amount_cents"] for l in lines if l["category"] == "ORDINARY")
        assert ordinary_sum == 9500000


class TestRunKindGating:
    def _open_year(self, api):
        fund = create_fund()
        create_partner(fund["id"], legal_name="LP")
        return create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)

    def test_final_run_rejected_while_tax_year_open(self, api):
        """PRD §3.4: "A `FINAL` run requires the tax year to be `BOOKS_CLOSED`,
        `ALLOCATED`, `UNDER_REVIEW`, or `APPROVED` — computing a `FINAL` run
        while the year is `OPEN` or `COMPLETED` is rejected with
        `ERR_TAX_YEAR_NOT_BOOKS_CLOSED` — and it uses the stored totals as-is
        while applying the tax year’s `APPROVED` special allocations whose
        half-open windows intersect the tax year."

        Design: Difficulty/cross_entity_state_dependency/final_run_requires_books_closed_tax_year
        """
        ty = self._open_year(api)
        resp = api.create_allocation_run(
            create_allocation_run_payload(ty["id"], ty["version"], run_kind="FINAL"),
            PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_TAX_YEAR_NOT_BOOKS_CLOSED)

    def test_provisional_run_accepted_while_tax_year_open(self, api):
        """PRD §3.4: "A `PROVISIONAL` run is allowed while the tax year is
        `OPEN` or `BOOKS_CLOSED`; it ignores all special allocations and
        annualizes each stored category total — the tax year’s net ordinary
        income, capital gain, and interest as persisted at compute time — by
        multiplying by 365 and dividing by the current day-of-year of the
        logical clock, rounding half-up to integer cents, with the day-of-year
        clamped between one and 365."

        Design: Difficulty/cross_entity_state_dependency/final_run_requires_books_closed_tax_year
        """
        ty = self._open_year(api)
        resp = api.create_allocation_run(
            create_allocation_run_payload(ty["id"], ty["version"], run_kind="PROVISIONAL"),
            PREPARER,
        )
        run = validate_success(resp, 201)
        assert_allocation_run(run)
        assert run["status"] == "COMPUTED"
        assert run["run_kind"] == "PROVISIONAL"


class TestReSupersedeConservation:
    def _scenario(self, api):
        """Canonical fund with a LOCKED FINAL run #1 staled by a settled
        LP1 -> LP3 transfer, then recomputed as run #2 and locked."""
        fund, partners = setup_fund_with_partners(fund_overrides=CANONICAL_FEE_FUND)
        ty = create_tax_year(fund["id"], year=2025, **CANONICAL_TOTALS)
        for key, amount in (("gp1", 10000000), ("lp1", 60000000), ("lp2", 30000000)):
            post_capital_event(partners[key]["id"], ty["id"], "CONTRIBUTION", amount, "2025-01-01")
        close_books(ty["id"])
        run1 = create_and_lock_final_run(ty["id"])
        lp3 = create_partner(
            fund["id"], legal_name="LP3", partner_type="US_INDIVIDUAL",
            residency_state="NY", ownership_pct_bps=1, capital_commitment_cents=1,
        )
        tr = create_and_confirm_transfer(
            fund["id"], partners["lp1"]["id"], lp3["id"],
            pct_bps=100, effective_date="2025-06-01", settlement_date="2025-06-10",
        )
        settle_transfer(tr["id"])
        run2 = create_allocation_run(ty["id"], run_kind="FINAL")
        return ty, run1, run2

    def test_new_run_supersedes_stale_run_and_locks(self, api):
        """PRD §3.5: "Staleness itself is always system-driven: a `LOCKED` run
        becomes `STALE` when an ownership transfer settles into its tax year or
        when the year is reopened, and in both cases packages snapshotting that
        run in `REVIEWED` or `APPROVED` preparation revert to `GENERATED`.
        Separately, creating a newer run for the same tax year moves any older
        `COMPUTED` or `STALE` run to `SUPERSEDED`, the run’s terminal state."

        Design: Difficulty/compensating_invariant/allocation_resupersede_zero_sum_conservation
        """
        ty, run1, run2 = self._scenario(api)
        locked = lock_run(run2["id"])
        assert locked["status"] == "LOCKED"
        run1_after = get_allocation_run(run1["id"])
        assert run1_after["status"] == "SUPERSEDED", (
            f"older STALE run must be SUPERSEDED by the newer run: {run1_after['status']}"
        )

    def test_category_totals_conserved_across_recompute(self, api):
        """PRD §3.4: "For every category, the run’s allocation lines sum to
        exactly the category total, so no cents drift."
        PRD §3.4: "A `FINAL` run requires the tax year to be `BOOKS_CLOSED`,
        `ALLOCATED`, `UNDER_REVIEW`, or `APPROVED` — computing a `FINAL` run
        while the year is `OPEN` or `COMPLETED` is rejected with
        `ERR_TAX_YEAR_NOT_BOOKS_CLOSED` — and it uses the stored totals as-is
        while applying the tax year’s `APPROVED` special allocations whose
        half-open windows intersect the tax year."

        Design: Difficulty/compensating_invariant/allocation_resupersede_zero_sum_conservation
        """
        ty, run1, run2 = self._scenario(api)
        lock_run(run2["id"])
        lines = _run_lines(api, run2["id"])
        for category, expected in (
            ("ORDINARY", 9500000), ("CAPITAL_GAIN", 20000000), ("INTEREST", 5000000),
        ):
            total = sum(l["amount_cents"] for l in lines if l["category"] == category)
            assert total == expected, (
                f"{category} lines must sum to the stored total {expected} despite "
                f"the ownership change: got {total}"
            )


class TestProvisionalAnnualization:
    def test_provisional_run_annualizes_and_ignores_specials(self, api):
        """PRD §3.4: "A `PROVISIONAL` run is allowed while the tax year is
        `OPEN` or `BOOKS_CLOSED`; it ignores all special allocations and
        annualizes each stored category total — the tax year’s net ordinary
        income, capital gain, and interest as persisted at compute time — by
        multiplying by 365 and dividing by the current day-of-year of the
        logical clock, rounding half-up to integer cents, with the day-of-year
        clamped between one and 365."

        Design: Corner/calculations/provisional_run_annualizes_and_ignores_specials
        """
        fund, partners = setup_fund_with_partners(fund_overrides=CANONICAL_FEE_FUND)
        ty = create_tax_year(fund["id"], year=2025, **CANONICAL_TOTALS)
        post_capital_event(partners["gp1"]["id"], ty["id"], "CONTRIBUTION", 10000000, "2025-01-01")
        create_and_approve_special_allocation(
            ty["id"], partners["gp1"]["id"],
            category="ORDINARY", target_pct_bps=5000,
            effective_from="2025-01-01", effective_to="2026-01-01",
        )
        set_clock("2025-07-02T00:00:00Z")  # day-of-year 183
        run = create_allocation_run(ty["id"], run_kind="PROVISIONAL")
        run_data = get_allocation_run(run["id"])
        assert run_data["ordinary_total_cents"] == 18948087, (
            f"9500000 annualized at day 183: {run_data['ordinary_total_cents']}"
        )
        assert run_data["interest_total_cents"] == 9972678
        assert run_data["capital_gain_total_cents"] == 39890710
        lines = _run_lines(api, run["id"])
        gp_ordinary = find_line(lines, partners["gp1"]["id"], "ORDINARY")
        assert gp_ordinary["amount_cents"] == 1894809, (
            f"PROVISIONAL ignores the APPROVED special; plain 10% pro-rata: {gp_ordinary['amount_cents']}"
        )


class TestProration:
    def test_proration_mid_year_transfer_allocation(self, api):
        """PRD §3.4: "Settled transfers are then applied in `effective_date`
        ascending order, ties broken by the transfer’s `created_at`: from the
        `effective_date` inclusive onward, the transferor’s share decreases by
        `pct_bps` and the transferee’s share increases by the same amount."
        PRD §3.4: "Each partner’s day-weighted share is the sum over the year’s
        day-segments of the basis-point share in effect during a segment
        multiplied by the number of days in that segment, and the ownership
        weight used downstream is that sum divided by 365, carried as an exact
        rational number with no intermediate rounding — only final per-partner
        money amounts are rounded."

        Design: Corner/calculations/proration_mid_year_transfer_allocation
        """
        fund = create_fund()
        t1 = create_partner(fund["id"], legal_name="T1", ownership_pct_bps=6000, residency_state="CA")
        t2 = create_partner(
            fund["id"], legal_name="T2", partner_type="US_ENTITY",
            ownership_pct_bps=4000, residency_state="DE",
        )
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=3650000)
        tr = create_and_confirm_transfer(
            fund["id"], t1["id"], t2["id"],
            pct_bps=2000, effective_date="2025-07-01", settlement_date="2025-07-02",
        )
        settle_transfer(tr["id"])
        close_books(ty["id"])
        run = create_allocation_run(ty["id"], run_kind="FINAL")
        lines = _run_lines(api, run["id"])
        # T1: 6000bps x 181d + 4000bps x 184d = 1822000 weighted day-bps
        # T2: 4000bps x 181d + 6000bps x 184d = 1828000 weighted day-bps
        assert find_line(lines, t1["id"], "ORDINARY")["amount_cents"] == 1822000
        assert find_line(lines, t2["id"], "ORDINARY")["amount_cents"] == 1828000
        total = sum(l["amount_cents"] for l in lines if l["category"] == "ORDINARY")
        assert total == 3650000, f"zero-sum conservation under proration: {total}"


class TestRunSupersedeAndLockRules:
    def test_new_run_supersedes_prior_computed_run(self, api):
        """PRD §3.4: "Creating the run automatically supersedes any existing
        `COMPUTED` or `STALE` run of the same tax year — those become
        `SUPERSEDED` — and increments the tax year’s `version`."
        PRD §3.4: "Each run receives a `run_seq`, a per-tax-year increasing
        sequence starting at one, and a `computed_at` timestamp read from the
        logical clock."

        Design: Corner/state_machines/new_run_supersedes_prior_computed_run
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        run1 = create_allocation_run(ty["id"], run_kind="PROVISIONAL")
        run2 = create_allocation_run(ty["id"], run_kind="PROVISIONAL")
        run1_after = get_allocation_run(run1["id"])
        assert run1_after["status"] == "SUPERSEDED"
        assert run2["run_seq"] == 2, f"second run of the tax year must have run_seq 2: {run2['run_seq']}"
        assert run2["status"] == "COMPUTED"

    def test_lock_provisional_run_rejected(self, api):
        """PRD §3.5: "Only a `FINAL` run can be locked — locking a `PROVISIONAL`
        run is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/lock_provisional_run_rejected
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        run = create_allocation_run(ty["id"], run_kind="PROVISIONAL")
        close_books(ty["id"])
        resp = api.lock_allocation_run(run["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_allocation_run(run["id"])["status"] == "COMPUTED"
        assert get_tax_year(ty["id"])["status"] == "BOOKS_CLOSED"


class TestRunEndpointRoles:
    def test_reviewer_cannot_create_allocation_run(self, api):
        """PRD §2.8: "Role authorization — the role is permitted for the
        endpoint and, for the entity-backed `Investor`, the `X-User-ID` equals
        the `partner_id` of the accessed resource on partner-scoped reads,
        acknowledgements, and ticket creation or reopening, else
        `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/funds/allocation-runs` | Compute a new allocation
        run; supersedes older computed or stale runs | TaxPreparer |"

        Design: Corner/rbac/reviewer_cannot_create_allocation_run
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        resp = api.create_allocation_run(
            create_allocation_run_payload(ty["id"], ty["version"], run_kind="PROVISIONAL"),
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_rep_cannot_lock_run(self, api):
        """PRD §2.8: "Role authorization — the role is permitted for the
        endpoint and, for the entity-backed `Investor`, the `X-User-ID` equals
        the `partner_id` of the accessed resource on partner-scoped reads,
        acknowledgements, and ticket creation or reopening, else
        `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/funds/allocation-runs/{runId}/lock` | Lock a
        computed `FINAL` run | TaxReviewer |"

        Design: Corner/rbac/rep_cannot_lock_run
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        close_books(ty["id"])
        run = create_allocation_run(ty["id"], run_kind="FINAL")
        resp = api.lock_allocation_run(run["id"], REP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_allocation_run(run["id"])["status"] == "COMPUTED"


class TestOptimisticConcurrency:
    def test_occ_stale_expected_version_rejected(self, api):
        """PRD §2.7: "The request must carry `expected_tax_year_version` as a
        non-optional input field, holding the client’s last observed `version`
        of the target tax year. If the tax year’s current `version` has
        advanced beyond what the client observed, the create is rejected with
        `ERR_STALE_TAX_YEAR_VERSION` (HTTP 412), preventing the client from
        superseding state it never saw — creating a run legitimately supersedes
        any existing `COMPUTED` or `STALE` run of that tax year, so a stale
        view must not silently discard a run the client never observed."

        Design: Corner/complexity_layers/occ_stale_expected_version_rejected
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        closed = close_books(ty["id"])
        current_version = closed["version"]
        resp_stale = api.create_allocation_run(
            create_allocation_run_payload(ty["id"], current_version - 1, run_kind="FINAL"),
            PREPARER,
        )
        validate_error(resp_stale, ApiErrorId.ERR_STALE_TAX_YEAR_VERSION, 412)
        resp_ok = api.create_allocation_run(
            create_allocation_run_payload(ty["id"], current_version, run_kind="FINAL"),
            PREPARER,
        )
        run = validate_success(resp_ok, 201)
        assert run["status"] == "COMPUTED"
        ty_after = get_tax_year(ty["id"])
        assert ty_after["version"] == current_version + 1, (
            "run creation increments the tax year version (PRD §3.4)"
        )
