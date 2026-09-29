"""Every write is visible to the very next read, with no settle time in between.

PRD §2.10: "Immediately after every single evaluation of that balance, the family's governance
posture is re-derived."
"""

from test_helpers import (
    RESERVE_CONTROLLER_USER_ID,
    create_accrual,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_service_contract,
    create_vintage,
    lock_period,
    move_clock,
    open_review,
    post_accrual,
    propose_accrual,
    read_family,
    read_service_contract,
    read_vintage,
)


def test_a_post_is_readable_everywhere_the_instant_it_returns(api):
    """The post response, the family ledger and the period guard all agree at once.

    PRD §3.3: "A successful post records the controller's identifier as `posted_by_user_id`."
    PRD §2.10 recomputes the ledger on that same transition: "The balance is recomputed when any
    accrual of the family moves from `PROPOSED` to `POSTED`" and, immediately afterwards,
    "If that ratio is at least 10000 basis points, `reserve_posture` becomes `CONSTRAINED`;
    otherwise, if it is at least 8000 basis points, `reserve_posture` becomes `ELEVATED`;
    otherwise it becomes `NORMAL`." At 2910000 cents against the 4000000-cent cap the ratio is
    7275 basis points, which clears neither threshold. PRD §3.1 reads the same freshly posted
    row through a different door: "if even one warranty accrual of the period still sits in
    `DRAFT` or `PROPOSED`, the request is refused with `ERR_UNPOSTED_ACCRUALS_REMAIN`".

    Design: Corner/consistency_model/corner_immediate_consistency_posted_accrual_is_visible_in_the_same_request
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog_family["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2029-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog_family["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )
    family = create_family(
        api,
        family_code="FAM-IM2",
        name="Immediate Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=4000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    cohort = create_vintage(
        api,
        family["id"],
        vintage_code="IM2-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-IM2-01",
        description="Immediate platform mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=30000,
    )
    accrual = create_accrual(
        api, period["id"], cohort["id"], method="ANALOG_BLEND", elapsed_exposure_bps=2000
    )
    propose_accrual(api, accrual["id"])
    lock_period(api, period["id"])

    posted = post_accrual(api, accrual["id"])
    assert posted["status"] == "POSTED"
    assert posted["posted_by_user_id"] == RESERVE_CONTROLLER_USER_ID
    assert posted["accrued_amount_cents"] == 2910000

    ledger = read_family(api, family["id"])
    assert ledger["warranty_reserve_balance_cents"] == 2910000
    assert ledger["reserve_posture"] == "NORMAL"

    reviewed = open_review(api, period["id"])
    assert reviewed["status"] == "ACTUARIAL_REVIEW"


def test_moving_the_clock_reprices_the_contract_before_the_next_read_lands(api):
    """Recognition, deferral and cohort exposure all follow the clock without a refresh step.

    PRD §2.5: "Moving the clock is not a passive act — it is the trigger for every
    time-dependent recomputation in the system, evaluated in this order. Each production
    vintage's `exposure_status` is recomputed against the new instant ... Every extended service
    contract still in `ACTIVE` status has its `months_elapsed`, `recognized_revenue_cents` and
    `deferred_revenue_cents` recomputed at the new clock position." The clock "before any client
    has set it, reads exactly `2026-08-01T00:00:00Z`", which puts a contract sold 2026-01-01 at
    seven whole months. PRD §3.6: "`recognized_revenue_cents` is `total_contract_price_cents`
    multiplied by `months_elapsed`, divided by `term_months`, rounded to the nearest integer",
    and "`deferred_revenue_cents` is `total_contract_price_cents` less
    `recognized_revenue_cents` less `refunded_revenue_cents`". PRD §3.2 fixes the cohort's
    reading: "it is `ACTIVE` while the logical clock is strictly earlier than
    `warranty_expiry_date` and `EXPIRED` from that date onward".

    Design: Corner/consistency_model/corner_immediate_consistency_clock_move_is_visible_on_the_next_read
    """
    family = create_family(
        api,
        family_code="FAM-CC",
        name="Clock Consistency Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    cohort = create_vintage(
        api,
        family["id"],
        vintage_code="CC-MY2025",
        units_shipped=400,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2026-10-31",
    )
    contract = create_service_contract(
        api,
        family["id"],
        contract_number="SC-CC-01",
        sold_date="2026-01-01",
        term_months=12,
        total_contract_price_cents=480000,
        recognition_method="STRAIGHT_LINE",
    )

    before = read_service_contract(api, contract["id"])
    assert before["months_elapsed"] == 7
    assert before["recognized_revenue_cents"] == 280000
    assert before["deferred_revenue_cents"] == 200000
    assert before["refunded_revenue_cents"] == 0
    assert (
        before["recognized_revenue_cents"]
        + before["deferred_revenue_cents"]
        + before["refunded_revenue_cents"]
        == 480000
    )
    assert read_vintage(api, cohort["id"])["exposure_status"] == "ACTIVE"

    move_clock(api, "2026-11-01T00:00:00Z")

    after = read_service_contract(api, contract["id"])
    assert after["months_elapsed"] == 10
    assert after["recognized_revenue_cents"] == 400000
    assert after["deferred_revenue_cents"] == 80000
    assert after["refunded_revenue_cents"] == 0
    assert after["status"] == "ACTIVE"
    assert (
        after["recognized_revenue_cents"]
        + after["deferred_revenue_cents"]
        + after["refunded_revenue_cents"]
        == 480000
    )
    assert read_vintage(api, cohort["id"])["exposure_status"] == "EXPIRED"
