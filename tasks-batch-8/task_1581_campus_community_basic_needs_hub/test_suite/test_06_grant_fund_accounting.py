"""Grant fund accounting: dual remainder bases, conservation across
approve/expire, close gating, closed-fund rejection, and the lifetime cap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fund_conservation,
    create_active_client,
    create_approved_grant,
    create_coordinator,
    create_fund,
    create_reviewer,
    create_under_review_grant,
    run_sweeps,
    set_clock,
    setup_client_at_lifetime_cap,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["hub_admin_headers"]


def _fund_with_one_approval(allocated=500000, award=150000, alias="river"):
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client, _, client_headers = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=1, monthly_income_cents=50000, housing_status="STABLE",
            dependents_under_18=0, receives_snap=False,
            receives_childcare_subsidy=False, food_insecurity_score=1,
            consent_confidential=True,
        ),
        client_overrides={"alias_name": alias},
    )
    fund = create_fund("Emergency FY26", allocated_cents=allocated)
    approved, fund_after = create_approved_grant(
        client, fund, reviewer,
        category="RENT", requested_cents=award, hardship_statement="eviction notice",
    )
    return {"coord": coord, "reviewer": reviewer, "client": client,
            "client_headers": client_headers, "fund": fund,
            "approved": approved, "fund_after": fund_after}


class TestFundRemainingDualBasis:
    def test_two_remaining_bases_diverge_after_approval(self, api):
        """PRD §3.5: "Two remainder readings derive from those:
        `remaining_committed_basis` is the allocation minus committed minus
        disbursed — the conservative reading, in which committed money is
        spoken for, and the only reading award sizing and exhaustion posture
        trust; `remaining_cash_basis` is the allocation minus disbursed alone
        — the optimistic reading reported for cash planning."

        Design: Difficulty/dual_variant_calc/fund_remaining_committed_vs_cash_basis
        """
        env = _fund_with_one_approval()
        fund = validate_success(
            api.get_grant_fund(env["fund"]["id"], env["reviewer"]), 200
        )
        assert fund["committed_cents"] == 150000
        assert fund["disbursed_cents"] == 0
        assert fund["remaining_committed_basis"] == 350000, (
            "500000 - 150000 committed - 0 disbursed"
        )
        assert fund["remaining_cash_basis"] == 500000, (
            "500000 - 0 disbursed — committed money still counted as present"
        )

    def test_bases_diverge_by_exactly_the_committed_amount(self, api):
        """PRD §3.5: "On a 500,000-cent fund with 100,000 committed and 50,000
        disbursed, the committed basis reads 350,000 while the cash basis
        reads 450,000, diverging by exactly the committed amount."

        Design: Difficulty/dual_variant_calc/fund_remaining_committed_vs_cash_basis
        """
        env = _fund_with_one_approval()
        fund = validate_success(
            api.get_grant_fund(env["fund"]["id"], env["reviewer"]), 200
        )
        assert (
            fund["remaining_cash_basis"] - fund["remaining_committed_basis"]
            == fund["committed_cents"] == 150000
        ), "same data, two readings, divergence pinned to the committed amount"
        assert fund["status"] == "OPEN"
        assert_fund_conservation(fund)


class TestApproveExpireConservation:
    def test_approval_moves_committed_and_preserves_invariant(self, api):
        """PRD §3.5: "On success the application moves to `APPROVED` with
        `approved_cents` and `approved_at` stamped; the fund's
        `committed_cents` grows by the approved amount, both remainder bases
        recompute, and the fund's `version` advances by one."
        PRD §3.5: "The approved amount is the smallest of four caps: the
        application's `requested_cents`; the 150,000-cent per-award cap; the
        fund's `remaining_committed_basis` read before this approval commits
        anything; and the client's remaining lifetime room ..."

        Design: Difficulty/compensating_invariant/approve_then_expire_restores_fund_committed_exactly
        """
        env = _fund_with_one_approval(allocated=300000, award=150000, alias="fenn")
        approved = env["approved"]
        assert approved["approved_cents"] == 150000

        fund = validate_success(
            api.get_grant_fund(env["fund"]["id"], env["reviewer"]), 200
        )
        assert fund["committed_cents"] == 150000
        assert fund["remaining_committed_basis"] == 150000
        assert_fund_conservation(fund)

    def test_expiry_sweep_restores_fund_to_pre_approval_state(self, api):
        """PRD §3.5: "An approval never disbursed in time expires instead: the
        sweep moves `APPROVED` to `EXPIRED` once the logical clock is strictly
        past the 72-hour mark, releasing `committed_cents`, recomputing the
        bases, advancing the fund's `version`, and running the same
        reopen-and-promote cascade."

        Design: Difficulty/compensating_invariant/approve_then_expire_restores_fund_committed_exactly
        """
        env = _fund_with_one_approval(allocated=300000, award=150000, alias="fenn")
        # approved_at == 2026-08-01T00:00:00Z; strictly past +72h.
        set_clock("2026-08-04T00:00:01Z")
        sweep = run_sweeps()
        assert sweep["grants_expired"] == 1

        fund = validate_success(
            api.get_grant_fund(env["fund"]["id"], env["reviewer"]), 200
        )
        assert fund["committed_cents"] == 0
        assert fund["disbursed_cents"] == 0
        assert fund["remaining_committed_basis"] == 300000, (
            "full restoration to the pre-approval figure, zero drift"
        )
        assert fund["status"] == "OPEN"
        assert_fund_conservation(fund)


def test_fund_close_blocked_until_review_resolved(api):
    """PRD §3.5: "Closing is rejected with `ERR_FUND_HAS_OPEN_APPLICATIONS`
    while any application against the fund occupies `SUBMITTED`, `QUEUED`,
    `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `APPROVED` — money still in
    flight must resolve first."

    Design: Corner/state_machines/fund_close_blocked_until_review_resolved
    """
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "fc"})
    fund = create_fund("FY26-c", allocated_cents=100000)
    grant = create_under_review_grant(
        client, fund, reviewer,
        category="FOOD", requested_cents=5000, hardship_statement="groceries",
    )

    res = api.close_grant_fund(fund["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_FUND_HAS_OPEN_APPLICATIONS, expected_status=409)

    validate_success(
        api.deny_grant(grant["id"], {"decision_rationale": "insufficient documentation"},
                       reviewer),
        200,
    )
    closed = validate_success(api.close_grant_fund(fund["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"


def test_fund_closed_rejects_application_create(api):
    """PRD §3.5: "The target fund must not be `CLOSED` (else
    `ERR_FUND_CLOSED`)."

    Design: Corner/errors/fund_closed_rejects_application_create
    """
    _, coord = create_coordinator()
    client, _, client_headers = create_active_client(
        coord, client_overrides={"alias_name": "fx"}
    )
    fund = create_fund("FY26-x", allocated_cents=100000)
    closed = validate_success(api.close_grant_fund(fund["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"

    res = api.create_grant_application(
        client["id"],
        {"fund_id": fund["id"], "category": "FOOD", "requested_cents": 5000,
         "hardship_statement": "x"},
        client_headers,
    )
    validate_error(res, ApiErrorId.ERR_FUND_CLOSED, expected_status=409)


def test_grant_approve_blocked_when_lifetime_cap_exhausted(api):
    """PRD §3.5: "the client's remaining lifetime room, 300,000 cents minus
    the client's `lifetime_grant_cents`. ... When the sized award would be
    zero or negative — fund remainder or lifetime room exhausted — approval is
    rejected with `ERR_AWARD_CAP_EXHAUSTED`."
    PRD §3.2: "`lifetime_grant_cents` sums the `approved_cents` of the
    client's `DISBURSED` emergency grant applications across all funds and all
    time."

    Design: Corner/errors/grant_approve_blocked_when_lifetime_cap_exhausted
    """
    env = setup_client_at_lifetime_cap()
    res = api.approve_grant(
        env["app3"]["id"],
        {"expected_fund_version": env["fund"]["version"]},
        env["reviewer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_AWARD_CAP_EXHAUSTED, expected_status=409)

    client = validate_success(
        api.get_client(env["client"]["id"], env["reviewer_headers"]), 200
    )
    assert client["lifetime_grant_cents"] == 300000, (
        "two DISBURSED 150000 awards exhaust the 300000 lifetime ceiling"
    )
    fund = validate_success(
        api.get_grant_fund(env["fund"]["id"], env["reviewer_headers"]), 200
    )
    assert fund["remaining_committed_basis"] == 200000, (
        "the fund was not the binding constraint"
    )
