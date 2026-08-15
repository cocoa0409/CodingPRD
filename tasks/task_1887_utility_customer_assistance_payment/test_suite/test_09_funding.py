"""Funding sources and allocations: waterfall selector policy, enrollment
re-validation, conservation invariant, and reporting."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_fund_conservation, assert_fund_allocation,
    create_account, setup_account_with_active_enrollment, create_fund, allocate,
    create_referral, set_clock, run_sweep, get_account,
    TEST_USERS,
    INCOME_TIER_1, INCOME_TIER_2,
)

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


class TestAllocationReferentialBeatsFiscal:
    def _lapsed_scenario(self, api):
        """TIER_1 enrollment activated 2026-08-01; OPEN fund FY2026 (50000); clock
        advanced to 2027-08-01 and swept so the enrollment is LAPSED and the fund
        is fiscal-year ineligible."""
        account, _app, enrollment = setup_account_with_active_enrollment(
            income=INCOME_TIER_1, service_address="32 Priority Pl")
        fund = create_fund(name="Utility Trust 2026", funder_type="UTILITY_TRUST",
                           appropriated_cents=50_000)
        set_clock("2027-08-01T00:00:00Z")
        return account, enrollment, fund

    def test_sweep_lapses_enrollment_at_recert_date(self, api):
        """PRD §3.3: "When the daily sweep finds the clock date has reached an
        `ACTIVE` enrollment's `recert_due_on`, the enrollment lapses: status
        becomes `LAPSED` and `lapsed_on` records the clock date."

        Design: Difficulty/priority_pair_validation_conflict/allocation_referential_beats_fiscal
        """
        _account, enrollment, _fund = self._lapsed_scenario(api)
        sweep = run_sweep()
        assert sweep["enrollments_lapsed"] == 1
        mid = validate_success(api.get_enrollment(enrollment["id"], SPECIALIST), 200)
        assert mid["status"] == "LAPSED"

    def test_enrollment_required_wins_over_insufficient_funds(self, api):
        """PRD §3.8: "The account must carry an `ACTIVE` enrollment — checked before
        fund sufficiency, with `ERR_ENROLLMENT_REQUIRED` (HTTP 422) when none
        exists."
        PRD §3.8: "The request is all-or-nothing: when the eligible pool's total
        `available_cents` falls short of the amount requested, the batch is rejected
        with `ERR_INSUFFICIENT_ASSISTANCE_FUNDS` (HTTP 422) and nothing is pledged."

        Design: Difficulty/priority_pair_validation_conflict/allocation_referential_beats_fiscal
        """
        account, _enrollment, _fund = self._lapsed_scenario(api)
        run_sweep()
        resp = api.create_fund_allocations(
            {"account_id": account["id"], "amount_cents": 100_000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_REQUIRED)


class TestAllocationRequiresCompletedReferral:
    def _scenario(self, api):
        """TIER_1 ACTIVE enrollment; LIHEAP FY2026 fund (100000) with
        requires_completed_referral; referral INITIATED but not completed."""
        account, _app, _enr = setup_account_with_active_enrollment(
            income=INCOME_TIER_1, service_address="52 Cross St")
        fund = create_fund(name="LIHEAP 2026", funder_type="LIHEAP",
                           appropriated_cents=100_000, eligible_tiers=["TIER_1"],
                           requires_completed_referral=True)
        referral = create_referral(account["id"], agency_code="COMM_ACTION")
        return account, fund, referral

    def test_referral_gated_fund_invisible_while_initiated(self, api):
        """PRD §3.8: "The waterfall then selects its eligible set: funds that are
        `OPEN`, whose `fiscal_year` equals the calendar year of the logical clock,
        whose `eligible_tiers` list contains the enrollment's tier, and — when a
        fund's `requires_completed_referral` is true — only where the account holds
        a `COMPLETED` AssistanceReferral."
        PRD §3.8: "The request is all-or-nothing: when the eligible pool's total
        `available_cents` falls short of the amount requested, the batch is rejected
        with `ERR_INSUFFICIENT_ASSISTANCE_FUNDS` (HTTP 422) and nothing is pledged."

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_completed_referral
        """
        account, _fund, _referral = self._scenario(api)
        resp = api.create_fund_allocations(
            {"account_id": account["id"], "amount_cents": 50_000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ASSISTANCE_FUNDS)

    def test_completed_referral_unlocks_fund(self, api):
        """PRD §3.9: "When the agency confirms the engagement, a
        `CustomerServiceRep` completes the referral: status moves from `INITIATED`
        to `COMPLETED`, `completed_on` records the clock date, and funds flagged
        `requires_completed_referral` become eligible to the account in the
        waterfall of §3.8."

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_completed_referral
        """
        account, fund, referral = self._scenario(api)
        completed = validate_success(api.complete_referral(referral["id"], CSR), 200)
        assert completed["status"] == "COMPLETED"
        rows = allocate(account["id"], 50_000)
        assert len(rows) == 1
        assert_fund_allocation(rows[0])
        assert rows[0]["funding_source_id"] == fund["id"]
        assert rows[0]["amount_cents"] == 50_000
        assert rows[0]["status"] == "PLEDGED"


class TestFundConservationAllocateReleaseRoundtrip:
    def _scenario(self, api):
        account, _app, _enr = setup_account_with_active_enrollment(
            income=INCOME_TIER_2, service_address="71 Ledger Ln")
        fund = create_fund(name="State Grant 2026", funder_type="STATE_GRANT",
                           appropriated_cents=100_000)
        return account, fund

    def test_allocate_moves_counters_and_holds_invariant(self, api):
        """PRD §3.8: "A fund is born `OPEN` with all counters at zero:
        `pledged_cents`, `disbursed_cents`, `released_cents`, and the derived
        `available_cents`, which is the appropriation minus pledged minus disbursed
        sums."
        PRD §3.8: "Fund counters move with the pledge: `pledged_cents` rises and
        `available_cents` falls correspondingly."

        Design: Difficulty/compensating_invariant/fund_conservation_allocate_release_roundtrip
        """
        account, fund = self._scenario(api)
        allocate(account["id"], 60_000)
        report = validate_success(api.get_funding_report(fund["id"], ADMIN), 200)
        assert report["pledged_cents"] == 60_000
        assert report["available_cents"] == 40_000
        assert report["disbursed_cents"] == 0
        assert report["released_cents"] == 0
        assert_fund_conservation(report)

    def test_release_restores_available_exactly(self, api):
        """PRD §3.8: "Releasing a `PLEDGED` allocation — by a `ProgramAdmin`, or by
        the system when its fund closes — moves it to `RELEASED` and restores its
        amount to the fund's `available_cents`".
        PRD §3.8: "The report honors a standing invariant: pledged plus disbursed
        plus released always equals the total ever allocated from the fund."

        Design: Difficulty/compensating_invariant/fund_conservation_allocate_release_roundtrip
        """
        account, fund = self._scenario(api)
        rows = allocate(account["id"], 60_000)
        validate_success(api.release_allocation(rows[0]["id"], ADMIN), 200)
        report = validate_success(api.get_funding_report(fund["id"], ADMIN), 200)
        assert report["pledged_cents"] == 0
        assert report["available_cents"] == 100_000, "available exactly restored"
        assert report["released_cents"] == 60_000
        assert report["pledged_cents"] + report["disbursed_cents"] \
            + report["released_cents"] == 60_000
        assert_fund_conservation(report)


def test_fund_close_releases_pledged_allocations(api):
    """PRD §3.8: "closing a fund — from `OPEN` or `SUSPENDED` — moves it to
    `CLOSED` and releases every `PLEDGED` allocation on it back into
    `available_cents`."

    Design: Corner/state_machines/fund_close_releases_pledged_allocations
    """
    account, _app, _enr = setup_account_with_active_enrollment(
        income=INCOME_TIER_2, service_address="10 Close Ct")
    fund = create_fund(name="Trust 2026", funder_type="UTILITY_TRUST",
                       appropriated_cents=80_000, eligible_tiers=["TIER_2"])
    rows = allocate(account["id"], 50_000)
    alloc_id = rows[0]["id"]
    closed = validate_success(api.close_funding_source(fund["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    alloc = validate_success(api.get_fund_allocation(alloc_id, ADMIN), 200)
    assert alloc["status"] == "RELEASED"
    report = validate_success(api.get_funding_report(fund["id"], ADMIN), 200)
    assert report["pledged_cents"] == 0
    assert report["released_cents"] == 50_000
    assert report["available_cents"] == 80_000
    assert_fund_conservation(report)


def test_fund_report_aggregation_with_disburse_remainder(api):
    """PRD §3.8: "A successful disbursement moves the allocation to `DISBURSED` and
    applies its `amount_cents` to the account: the arrearage falls by the smaller
    of the amount and the current `arrearage_balance_cents`, and any remainder
    flows into `credit_balance_cents`."
    PRD §3.8: "returning its `funding_source_id`, the `appropriated_cents`, the
    summed `pledged_cents`, `disbursed_cents`, and `released_cents` across all of
    its allocations in every status for all time, the derived `available_cents`,
    and an `allocation_count` of every allocation row on the fund."

    Design: Corner/calculations/fund_report_aggregation_with_disburse_remainder
    """
    account, _app, _enr = setup_account_with_active_enrollment(
        income=INCOME_TIER_2, arrearage_cents=25_000, service_address="24 Report Rd")
    fund = create_fund(name="State 2026", funder_type="STATE_GRANT",
                       appropriated_cents=100_000)
    alloc1 = allocate(account["id"], 30_000)[0]
    allocate(account["id"], 20_000)
    disbursed = validate_success(api.disburse_allocation(alloc1["id"], ADMIN), 200)
    assert disbursed["status"] == "DISBURSED"
    account = get_account(account["id"])
    assert account["arrearage_balance_cents"] == 0
    assert account["credit_balance_cents"] == 5_000, "remainder routes to credit"
    report = validate_success(api.get_funding_report(fund["id"], ADMIN), 200)
    assert report["pledged_cents"] == 20_000
    assert report["disbursed_cents"] == 30_000
    assert report["released_cents"] == 0
    assert report["available_cents"] == 50_000
    assert report["allocation_count"] == 2
    assert_fund_conservation(report)


def test_disburse_blocked_after_enrollment_lapse(api):
    """PRD §3.8: "Disbursing requires the allocation to still be `PLEDGED` — else
    `ERR_ALLOCATION_NOT_PLEDGED` (HTTP 409) — and then re-validates the pinned
    enrollment: if it is no longer `ACTIVE`, disbursement fails with
    `ERR_ENROLLMENT_NO_LONGER_ACTIVE` (HTTP 422)."

    Design: Corner/validations/disburse_blocked_after_enrollment_lapse
    """
    account, _app, _enr = setup_account_with_active_enrollment(
        income=INCOME_TIER_2, service_address="42 Revalidate Rd")
    fund = create_fund(name="Trust 2026", funder_type="UTILITY_TRUST",
                       appropriated_cents=100_000, eligible_tiers=["TIER_1", "TIER_2"])
    alloc_id = allocate(account["id"], 30_000)[0]["id"]
    set_clock("2027-08-01T00:00:00Z")
    run_sweep()  # enrollment lapses at its recert date
    resp = api.disburse_allocation(alloc_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NO_LONGER_ACTIVE)
    stayed = validate_success(api.get_fund_allocation(alloc_id, ADMIN), 200)
    assert stayed["status"] == "PLEDGED"


def test_allocation_double_disburse_rejected(api):
    """PRD §3.8: "Disbursing requires the allocation to still be `PLEDGED` — else
    `ERR_ALLOCATION_NOT_PLEDGED` (HTTP 409)".
    PRD §3.8: "the arrearage falls by the smaller of the amount and the current
    `arrearage_balance_cents`, and any remainder flows into `credit_balance_cents`."

    Design: Corner/validations/allocation_double_disburse_rejected
    """
    account, _app, _enr = setup_account_with_active_enrollment(
        income=INCOME_TIER_2, service_address="49 Doubledisb Dr")
    fund = create_fund(name="State 2026", funder_type="STATE_GRANT",
                       appropriated_cents=100_000, eligible_tiers=["TIER_2"])
    alloc_id = allocate(account["id"], 30_000)[0]["id"]
    validate_success(api.disburse_allocation(alloc_id, ADMIN), 200)
    resp = api.disburse_allocation(alloc_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_PLEDGED)
    account = get_account(account["id"])
    assert account["credit_balance_cents"] == 30_000, (
        "30000 disbursed against zero arrearage credits the account exactly once")


def test_selector_waterfall_tiebreak_created_at(api):
    """PRD §3.8: "Eligible funds are consumed in `priority_rank` ascending order,
    ties broken by `created_at` ascending, never by identifier."
    PRD §3.8: "creating one FundAllocation row per contributing fund, each for at
    least one cent, all sharing a single `batch_id` that groups the batch, each
    recording its 1-based fill position in `allocation_sequence`".

    Design: Corner/cross_cutting_layers/selector_waterfall_tiebreak_created_at
    """
    account, _app, _enr = setup_account_with_active_enrollment(
        income=INCOME_TIER_1, service_address="82 Selector St")
    f1 = create_fund(name="F1", funder_type="STATE_GRANT", appropriated_cents=50_000,
                     priority_rank=5, eligible_tiers=["TIER_1"])  # created 2026-08-01
    set_clock("2026-08-02T00:00:00Z")
    f2 = create_fund(name="F2", funder_type="UTILITY_TRUST", appropriated_cents=50_000,
                     priority_rank=5, eligible_tiers=["TIER_1"])  # created one day later
    rows = allocate(account["id"], 60_000)
    assert len(rows) == 2
    ordered = sorted(rows, key=lambda r: r["allocation_sequence"])
    assert ordered[0]["funding_source_id"] == f1["id"], (
        "the earlier-created fund wins the rank tie")
    assert ordered[0]["amount_cents"] == 50_000
    assert ordered[0]["allocation_sequence"] == 1
    assert ordered[1]["funding_source_id"] == f2["id"]
    assert ordered[1]["amount_cents"] == 10_000
    assert ordered[1]["allocation_sequence"] == 2
    assert ordered[0]["batch_id"] == ordered[1]["batch_id"]


def test_suspended_fund_leaves_waterfall(api):
    """PRD §3.8: "Suspending an `OPEN` fund moves it to `SUSPENDED` and removes it
    from waterfall eligibility".
    PRD §3.8: "The request is all-or-nothing: when the eligible pool's total
    `available_cents` falls short of the amount requested, the batch is rejected
    with `ERR_INSUFFICIENT_ASSISTANCE_FUNDS` (HTTP 422) and nothing is pledged."

    Design: Corner/cross_cutting_layers/suspended_fund_leaves_waterfall
    """
    account, _app, _enr = setup_account_with_active_enrollment(
        income=INCOME_TIER_1, service_address="84 Suspend St")
    fund = create_fund(name="Trust 2026", funder_type="UTILITY_TRUST",
                       appropriated_cents=100_000, eligible_tiers=["TIER_1"])
    suspended = validate_success(api.suspend_funding_source(fund["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    resp = api.create_fund_allocations(
        {"account_id": account["id"], "amount_cents": 10_000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ASSISTANCE_FUNDS)
    rows, meta = validate_paginated(
        api.list_fund_allocations(ADMIN, params={"account_id": account["id"]}))
    assert meta["total_count"] == 0, "all-or-nothing: no partial pledge"
