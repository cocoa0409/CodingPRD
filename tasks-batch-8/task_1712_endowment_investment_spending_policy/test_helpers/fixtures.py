"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
(the runner restarts the server before each test) using only PRD-declared
endpoints. Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Common context dict keys: pool, manager, fund, donor, gift, policy,
distribution, exception, payout, valuation.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    bulk_upsert_allocations_payload,
    create_allocation_item,
    create_distribution_payload,
    create_donor_payload,
    create_exception_payload,
    create_fund_payload,
    create_gift_payload,
    create_manager_payload,
    create_manager_report_payload,
    create_payout_payload,
    create_policy_payload,
    create_pool_payload,
    create_report_payload,
    create_valuation_payload,
)
from .test_users import (
    make_board_member_headers,
    make_development_officer_headers,
    make_investment_officer_headers,
    make_program_manager_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
IO = TEST_USERS["io_headers"]
DEV = TEST_USERS["dev_headers"]
BOARD = TEST_USERS["board_headers"]
PROGRAM = TEST_USERS["program_headers"]


# ─── Tier 0: Atomic step helpers ────────────────────────────────────────────

def create_pool(pool_name="Test Pool", inception_fiscal_year=2026) -> dict:
    res = api_client.create_pool(
        create_pool_payload(pool_name=pool_name, inception_fiscal_year=inception_fiscal_year),
        ADMIN,
    )
    return get_success_data(res)


def get_pool(pool_id) -> dict:
    """Fresh read of a pool — the source of the current OCC version (PRD §2.7)."""
    return get_success_data(api_client.get_pool(pool_id, IO))


def suspend_pool(pool_id) -> dict:
    return get_success_data(api_client.suspend_pool(pool_id, ADMIN))


def resume_pool(pool_id) -> dict:
    return get_success_data(api_client.resume_pool(pool_id, ADMIN))


def set_target_allocations(pool_id, items=None) -> list:
    """Replace the pool's target allocation set (PRD §3.9). Defaults to 100% CASH."""
    if items is None:
        items = [create_allocation_item("CASH", 10_000, 500)]
    res = api_client.bulk_upsert_allocations(
        bulk_upsert_allocations_payload(pool_id, items), ADMIN,
    )
    return get_success_data(res)


def create_adopted_policy(
    pool_id,
    spending_rate_bps=500,
    smoothing_window_quarters=4,
    band_floor_bps=0,
    band_cap_bps=10_000,
    effective_from_fiscal_year=2026,
    proposer_user_id="io-1",
    adopter_user_id="bm-1",
) -> dict:
    """Create a DRAFT policy then adopt it (proposer and adopter differ, PRD §3.3)."""
    policy = get_success_data(api_client.create_policy(
        create_policy_payload(
            pool_id,
            spending_rate_bps=spending_rate_bps,
            smoothing_window_quarters=smoothing_window_quarters,
            band_floor_bps=band_floor_bps,
            band_cap_bps=band_cap_bps,
            effective_from_fiscal_year=effective_from_fiscal_year,
        ),
        make_investment_officer_headers(proposer_user_id),
    ))
    pool_version = get_pool(pool_id)["version"]
    return get_success_data(api_client.adopt_policy(
        policy["id"],
        {"expected_pool_version": pool_version},
        make_board_member_headers(adopter_user_id),
    ))


def create_engaged_manager(
    pool_id,
    manager_name="Manager One",
    asset_class="US_EQUITY",
    benchmark_code="SPX",
    coverage_start_quarter=1,
) -> dict:
    manager = get_success_data(api_client.create_manager(
        create_manager_payload(
            pool_id,
            manager_name=manager_name,
            asset_class=asset_class,
            benchmark_code=benchmark_code,
            coverage_start_quarter=coverage_start_quarter,
        ),
        IO,
    ))
    return get_success_data(api_client.engage_manager(manager["id"], IO))


def create_donor(donor_name="Donor One", donor_type="INDIVIDUAL") -> dict:
    return get_success_data(api_client.create_donor(
        create_donor_payload(donor_name=donor_name, donor_type=donor_type), DEV,
    ))


def create_fund(
    pool_id,
    fund_code="FUND-1",
    fund_name="Test Fund",
    endowment_class="TRUE_ENDOWMENT",
    term_end_quarter_index=None,
    purpose_restriction="UNRESTRICTED",
) -> dict:
    payload = create_fund_payload(
        pool_id,
        fund_code=fund_code,
        fund_name=fund_name,
        endowment_class=endowment_class,
        purpose_restriction=purpose_restriction,
    )
    if term_end_quarter_index is not None:
        payload["term_end_quarter_index"] = term_end_quarter_index
    return get_success_data(api_client.create_fund(payload, DEV))


def create_gift(
    fund_id,
    donor_id,
    external_ref,
    gift_type="CORPUS",
    amount_cents=10_000_000,
) -> dict:
    return get_success_data(api_client.create_gift(
        create_gift_payload(
            fund_id, donor_id,
            external_ref=external_ref, gift_type=gift_type, amount_cents=amount_cents,
        ),
        DEV,
    ))


def activate_fund(fund_id) -> dict:
    return get_success_data(api_client.activate_fund(fund_id, DEV))


def receive_gift(gift_id) -> dict:
    return get_success_data(api_client.receive_gift(gift_id, DEV))


def file_manager_report(
    manager_id,
    quarter_index,
    beginning_mv_cents,
    ending_mv_cents,
    flows=None,
    benchmark_return_bps=0,
) -> dict:
    return get_success_data(api_client.create_manager_report(
        create_manager_report_payload(
            manager_id, quarter_index,
            beginning_mv_cents=beginning_mv_cents,
            ending_mv_cents=ending_mv_cents,
            flows=[] if flows is None else flows,
            benchmark_return_bps=benchmark_return_bps,
        ),
        IO,
    ))


def open_valuation(pool_id, estimated_pool_market_value_cents) -> dict:
    return get_success_data(api_client.create_valuation(
        create_valuation_payload(
            pool_id, estimated_pool_market_value_cents=estimated_pool_market_value_cents,
        ),
        IO,
    ))


def finalize_valuation(valuation_id, pool_id, final_pool_market_value_cents) -> dict:
    """Finalize with a fresh OCC read of the pool version (PRD §2.7)."""
    pool_version = get_pool(pool_id)["version"]
    return get_success_data(api_client.finalize_valuation(
        valuation_id,
        {
            "final_pool_market_value_cents": final_pool_market_value_cents,
            "expected_pool_version": pool_version,
        },
        IO,
    ))


def finalize_open_quarter(pool_id, final_pool_market_value_cents, reports=(), estimated_pool_market_value_cents=None) -> dict:
    """File this quarter's manager reports, open the PRELIMINARY valuation, finalize it.

    reports: iterable of dicts with keys manager_id, beginning_mv_cents,
    ending_mv_cents, flows (optional), benchmark_return_bps (optional).
    Returns the FINAL valuation.
    """
    pool = get_pool(pool_id)
    quarter = pool["current_quarter_index"] + 1
    for report in reports:
        file_manager_report(
            report["manager_id"],
            quarter,
            report["beginning_mv_cents"],
            report["ending_mv_cents"],
            flows=report.get("flows", []),
            benchmark_return_bps=report.get("benchmark_return_bps", 0),
        )
    if estimated_pool_market_value_cents is None:
        estimated_pool_market_value_cents = final_pool_market_value_cents
    valuation = open_valuation(pool_id, estimated_pool_market_value_cents)
    return finalize_valuation(valuation["id"], pool_id, final_pool_market_value_cents)


# ─── Distribution / exception / payout / report step helpers ────────────────

def create_distribution(fund_id, fiscal_year, creator_user_id="dev-1") -> dict:
    return get_success_data(api_client.create_distribution(
        create_distribution_payload(fund_id, fiscal_year=fiscal_year),
        make_development_officer_headers(creator_user_id),
    ))


def propose_distribution(distribution_id, user_id="dev-1") -> dict:
    return get_success_data(api_client.propose_distribution(
        distribution_id, make_development_officer_headers(user_id),
    ))


def request_revision_distribution(distribution_id, user_id="bm-1") -> dict:
    return get_success_data(api_client.request_revision_distribution(
        distribution_id, make_board_member_headers(user_id),
    ))


def repropose_distribution(distribution_id, user_id="dev-1") -> dict:
    return get_success_data(api_client.repropose_distribution(
        distribution_id, make_development_officer_headers(user_id),
    ))


def approve_distribution(distribution_id, user_id="bm-1") -> dict:
    return get_success_data(api_client.approve_distribution(
        distribution_id, make_board_member_headers(user_id),
    ))


def distribute_distribution(distribution_id) -> dict:
    return get_success_data(api_client.distribute_distribution(distribution_id, IO))


def cancel_distribution(distribution_id, user_id="dev-1", role="DevelopmentOfficer") -> dict:
    headers = (make_development_officer_headers(user_id)
               if role == "DevelopmentOfficer"
               else make_board_member_headers(user_id))
    return get_success_data(api_client.cancel_distribution(distribution_id, headers))


def request_exception(fund_id, fiscal_year, requested_amount_cents,
                      justification="bridge funding", requester_user_id="dev-1") -> dict:
    return get_success_data(api_client.create_exception(
        create_exception_payload(
            fund_id,
            fiscal_year=fiscal_year,
            requested_amount_cents=requested_amount_cents,
            justification=justification,
        ),
        make_development_officer_headers(requester_user_id),
    ))


def endorse_exception(exception_id, endorser_user_id="io-2") -> dict:
    return get_success_data(api_client.endorse_exception(
        exception_id, make_investment_officer_headers(endorser_user_id),
    ))


def approve_exception(exception_id, approved_amount_cents, approver_user_id="bm-1") -> dict:
    return get_success_data(api_client.approve_exception(
        exception_id,
        {"approved_amount_cents": approved_amount_cents},
        make_board_member_headers(approver_user_id),
    ))


def rescind_exception(exception_id, user_id="bm-2") -> dict:
    return get_success_data(api_client.rescind_exception(
        exception_id, make_board_member_headers(user_id),
    ))


def create_payout(distribution_id, program_code, program_purpose, allocated_amount_cents) -> dict:
    return get_success_data(api_client.create_payout(
        create_payout_payload(
            distribution_id,
            program_code=program_code,
            program_purpose=program_purpose,
            allocated_amount_cents=allocated_amount_cents,
        ),
        DEV,
    ))


def disburse_payout(payout_id) -> dict:
    return get_success_data(api_client.disburse_payout(payout_id, DEV))


def report_payout_spending(payout_id, spent_amount_cents, user_id="pm-1") -> dict:
    return get_success_data(api_client.report_spending(
        payout_id,
        {"spent_amount_cents": spent_amount_cents},
        make_program_manager_headers(user_id),
    ))


def create_annual_report(pool_id, report_type, fiscal_year, fund_id=None,
                         author_user_id="dev-1", author_role="DevelopmentOfficer") -> dict:
    payload = create_report_payload(pool_id, report_type=report_type, fiscal_year=fiscal_year)
    if fund_id is not None:
        payload["fund_id"] = fund_id
    headers = (make_development_officer_headers(author_user_id)
               if author_role == "DevelopmentOfficer"
               else make_investment_officer_headers(author_user_id))
    return get_success_data(api_client.create_report(payload, headers))


def submit_report_review(report_id, user_id="dev-1", role="DevelopmentOfficer") -> dict:
    headers = (make_development_officer_headers(user_id)
               if role == "DevelopmentOfficer"
               else make_investment_officer_headers(user_id))
    return get_success_data(api_client.submit_review_report(report_id, headers))


def publish_report(report_id, user_id="bm-1") -> dict:
    return get_success_data(api_client.publish_report(
        report_id, make_board_member_headers(user_id),
    ))


# ─── Tier 1/2: Composite world builders ──────────────────────────────────────

def setup_pool_world(pool_name="Test Pool", inception_fiscal_year=2026,
                     asset_class="US_EQUITY", with_manager=True,
                     manager_coverage_start=1) -> dict:
    """Pool + 100% single-class target allocation + (optional) engaged manager."""
    ctx = {}
    ctx["pool"] = create_pool(pool_name=pool_name, inception_fiscal_year=inception_fiscal_year)
    set_target_allocations(
        ctx["pool"]["id"], [create_allocation_item(asset_class, 10_000, 500)],
    )
    if with_manager:
        ctx["manager"] = create_engaged_manager(
            ctx["pool"]["id"], asset_class=asset_class,
            coverage_start_quarter=manager_coverage_start,
        )
    return ctx


def setup_zero_manager_pool(pool_name="Test Pool", inception_fiscal_year=2026) -> dict:
    """Pool + 100% CASH allocation and no managers (finalize gates pass vacuously)."""
    return setup_pool_world(
        pool_name=pool_name, inception_fiscal_year=inception_fiscal_year,
        asset_class="CASH", with_manager=False,
    )


def setup_funded_world(corpus_cents=10_000_000, quarter1_ending_mv=None,
                       endowment_class="TRUE_ENDOWMENT", term_end_quarter_index=None,
                       purpose_restriction="UNRESTRICTED", fund_code="FUND-1",
                       pool_name="Test Pool", with_policy=False,
                       policy_overrides=None) -> dict:
    """Pool + allocation + engaged manager + ACTIVE fund whose CORPUS gift
    unitizes at the Q1 finalize (inception price; pre-flow units are 0).

    quarter1_ending_mv defaults to corpus_cents (flat price 100000 millicents).
    """
    if quarter1_ending_mv is None:
        quarter1_ending_mv = corpus_cents
    ctx = setup_pool_world(pool_name=pool_name)
    if with_policy:
        ctx["policy"] = create_adopted_policy(
            ctx["pool"]["id"], **(policy_overrides or {}),
        )
    ctx["fund"] = create_fund(
        ctx["pool"]["id"], fund_code=fund_code,
        endowment_class=endowment_class,
        term_end_quarter_index=term_end_quarter_index,
        purpose_restriction=purpose_restriction,
    )
    ctx["donor"] = create_donor()
    ctx["gift"] = create_gift(
        ctx["fund"]["id"], ctx["donor"]["id"], external_ref="GIFT-SEED",
        gift_type="CORPUS", amount_cents=corpus_cents,
    )
    ctx["fund"] = activate_fund(ctx["fund"]["id"])
    ctx["gift"] = receive_gift(ctx["gift"]["id"])
    ctx["valuation_q1"] = finalize_open_quarter(
        ctx["pool"]["id"],
        quarter1_ending_mv,
        reports=[{
            "manager_id": ctx["manager"]["id"],
            "beginning_mv_cents": 0,
            "ending_mv_cents": quarter1_ending_mv,
            "flows": [{"day_offset": 0, "amount_cents": quarter1_ending_mv}],
        }],
    )
    ctx["fund"] = get_success_data(api_client.get_fund(ctx["fund"]["id"], IO))
    return ctx


def setup_underwater_world(corpus_cents=10_000_000, crash_ending_mv=4_000_000,
                           with_policy=True, policy_overrides=None, **kwargs) -> dict:
    """Funded world + a Q2 crash finalize that leaves the fund underwater
    (market value below historic gift value) and SPENDING_SUSPENDED (PRD §3.4)."""
    ctx = setup_funded_world(
        corpus_cents=corpus_cents, quarter1_ending_mv=corpus_cents,
        with_policy=with_policy, policy_overrides=policy_overrides, **kwargs,
    )
    ctx["valuation_q2"] = finalize_open_quarter(
        ctx["pool"]["id"],
        crash_ending_mv,
        reports=[{
            "manager_id": ctx["manager"]["id"],
            "beginning_mv_cents": corpus_cents,
            "ending_mv_cents": crash_ending_mv,
        }],
    )
    ctx["fund"] = get_success_data(api_client.get_fund(ctx["fund"]["id"], IO))
    return ctx


def setup_exception_world(requested_amount_cents=300_000, approved_amount_cents=300_000,
                          fiscal_year=2026, **kwargs) -> dict:
    """Underwater world + an exception carried REQUESTED -> ENDORSED -> APPROVED
    (three distinct operators, PRD §3.6). Fund posture ends EXCEPTION_ACTIVE."""
    ctx = setup_underwater_world(**kwargs)
    ctx["exception"] = request_exception(
        ctx["fund"]["id"], fiscal_year, requested_amount_cents,
    )
    ctx["exception"] = endorse_exception(ctx["exception"]["id"])
    ctx["exception"] = approve_exception(ctx["exception"]["id"], approved_amount_cents)
    ctx["fund"] = get_success_data(api_client.get_fund(ctx["fund"]["id"], IO))
    return ctx


def setup_distributed_world(corpus_cents=10_000_000, fiscal_year=2026,
                            purpose_restriction="UNRESTRICTED",
                            policy_overrides=None, pool_name="Test Pool") -> dict:
    """Funded world + adopted policy + a distribution taken
    PROJECTED -> PROPOSED -> APPROVED -> DISTRIBUTED (PRD §3.5)."""
    ctx = setup_funded_world(
        corpus_cents=corpus_cents, quarter1_ending_mv=corpus_cents,
        purpose_restriction=purpose_restriction, pool_name=pool_name,
        with_policy=True, policy_overrides=policy_overrides,
    )
    ctx["distribution"] = create_distribution(ctx["fund"]["id"], fiscal_year)
    ctx["distribution"] = propose_distribution(ctx["distribution"]["id"])
    ctx["distribution"] = approve_distribution(ctx["distribution"]["id"])
    ctx["distribution"] = distribute_distribution(ctx["distribution"]["id"])
    ctx["fund"] = get_success_data(api_client.get_fund(ctx["fund"]["id"], IO))
    return ctx


def setup_disbursed_payout_world(allocated_amount_cents=200_000, program_code="LIB-1",
                                 program_purpose="RESEARCH", **kwargs) -> dict:
    """Distributed world + a payout created and disbursed (PRD §3.7)."""
    ctx = setup_distributed_world(**kwargs)
    ctx["payout"] = create_payout(
        ctx["distribution"]["id"], program_code, program_purpose, allocated_amount_cents,
    )
    ctx["payout"] = disburse_payout(ctx["payout"]["id"])
    return ctx
