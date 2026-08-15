"""The CGA reserve fund: singleton defaults, two coverage bases, the execution
gate's pinned evaluation order, the floored-coverage boundary, OCC, and the
contribution/withdrawal compensating invariant."""
from test_helpers import (
    STD_CGA_RESERVE_REQUIREMENT_CENTS,
    ApiErrorId,
    assert_reserve_fund,
    contribute_reserve,
    create_gift_asset_payload,
    make_active_agreement,
    make_active_rate_table,
    make_donor,
    make_draft_agreement,
    make_funded_cga_with_reserve,
    make_verified_designation,
    reserve_version,
    validate_error,
    validate_success,
    withdraw_reserve,
)


def _executed_cga_prefunded(api, gift_admin_headers):
    """CGA (10M gift, 600bps, QUARTERLY, age 80) EXECUTED with the reserve
    pre-funded to exactly its requirement; not yet funded (no assets)."""
    donor = make_donor(full_name="Coverage Basis")
    make_active_rate_table()
    agreement = make_draft_agreement(
        donor["id"], vehicle_type="CGA", payout_rate_bps=600
    )
    make_verified_designation(agreement["id"])
    contribute_reserve(STD_CGA_RESERVE_REQUIREMENT_CENTS)
    executed = validate_success(api.execute_gift_agreement(agreement["id"], gift_admin_headers))
    return donor, executed


def _receive_full_cash(api, agreement, estate_manager_headers, amount=10000000):
    asset = validate_success(
        api.create_gift_asset(
            create_gift_asset_payload(
                gift_agreement_id=agreement["id"],
                asset_kind="CASH",
                pledged_value_cents=amount,
            ),
            estate_manager_headers,
        ),
        201,
    )
    validate_success(
        api.transition_gift_asset(asset["id"], {"action": "RECEIVE"}, estate_manager_headers)
    )
    return asset


class TestReserveSingletonDefaults:
    def test_reserve_fund_singleton_default_read(self, api, finance_steward_headers):
        """PRD §2.8: "The system maintains a single `ReserveFund` — a singleton
        ledger instantiated at server startup with `name` equal to
        `CGA_RESERVE`, `balance_cents` equal to zero, and `posture` equal to
        `SOLVENT`."
        PRD §2.8: "Third, `booked_coverage_bps` is null when
        `booked_target_cents` is zero, and otherwise the floored integer value
        of `balance_cents` times 10000 divided by `booked_target_cents`."

        Design: Corner/endpoints/reserve_fund_singleton_default_read
        """
        data = validate_success(api.get_reserve_fund(finance_steward_headers))
        assert_reserve_fund(data)
        assert data["name"] == "CGA_RESERVE"
        assert data["balance_cents"] == 0
        assert data["booked_target_cents"] == 0
        assert data["projected_target_cents"] == 0
        assert data["booked_coverage_bps"] is None
        assert data["posture"] == "SOLVENT"


class TestBookedVsProjectedBases:
    def test_executed_unfunded_cga_counted_only_in_projected_basis(
        self, api, compliance_headers, gift_admin_headers
    ):
        """PRD §2.8: "First, `booked_target_cents` is the sum of
        `reserve_requirement_cents` over agreements whose `vehicle_type` is
        `CGA` and whose `status` is one of `FUNDED`, `ACTIVE`, or `SUSPENDED` —
        the statutory basis. Second, `projected_target_cents` is
        `booked_target_cents` plus the sum of `reserve_requirement_cents` over
        `CGA` agreements in `EXECUTED` status — the forward-looking basis."

        Design: Difficulty/dual_variant_calc/reserve_coverage_booked_vs_projected
        """
        _donor, agreement = _executed_cga_prefunded(api, gift_admin_headers)
        assert agreement["status"] == "EXECUTED"
        pool = validate_success(api.get_reserve_fund(compliance_headers))
        # EXECUTED CGA is excluded from the statutory basis...
        assert pool["booked_target_cents"] == 0
        # ...and included in the forward-looking basis.
        assert pool["projected_target_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS
        assert pool["booked_coverage_bps"] is None
        assert pool["posture"] == "SOLVENT"

    def test_funding_moves_requirement_into_booked_basis(
        self, api, compliance_headers, gift_admin_headers, estate_manager_headers
    ):
        """PRD §3.5: "At the end of every receipt or appraisal transition on an
        agreement-linked asset, the system re-evaluates the funding threshold:
        if the agreement is `EXECUTED`, is not a `BEQUEST` (bequests are
        unfunded by definition and mature on death), and `received_value_cents`
        is at least `gift_amount_cents` — an inclusive boundary — the agreement
        auto-transitions to `FUNDED`, and the reserve fund's booked and
        projected targets are recomputed (a CGA requirement joins the booked
        set and leaves the projected-only set)."

        Design: Difficulty/dual_variant_calc/reserve_coverage_booked_vs_projected
        """
        _donor, agreement = _executed_cga_prefunded(api, gift_admin_headers)
        _receive_full_cash(api, agreement, estate_manager_headers)
        after = validate_success(api.get_gift_agreement(agreement["id"], compliance_headers))
        assert after["status"] == "FUNDED"
        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["booked_target_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS
        assert pool["projected_target_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS
        assert pool["booked_coverage_bps"] == 10000
        assert pool["posture"] == "SOLVENT"


class TestReserveGateEvaluationOrder:
    def _setup_solvent_pool_and_candidate(self, api, gift_admin_headers, estate_manager_headers):
        """CGA-1 EXECUTED->FUNDED with balance exactly equal to its booked
        requirement (coverage exactly 10000, SOLVENT); CGA-2 DRAFT with a
        VERIFIED PRIMARY_1 designation."""
        donor = make_donor(full_name="Eval Order")
        make_active_rate_table()
        cga1 = make_funded_cga_with_reserve(donor["id"])
        cga2 = make_draft_agreement(
            donor["id"], vehicle_type="CGA", payout_rate_bps=600
        )
        make_verified_designation(cga2["id"])
        return cga1, cga2

    def test_candidate_requirement_blocks_its_own_execution(
        self, api, compliance_headers, gift_admin_headers, estate_manager_headers
    ):
        """PRD §3.3: "for `CGA` agreements only, the reserve gate — the fund's
        `balance_cents` must be at least `booked_target_cents` plus the summed
        `reserve_requirement_cents` of all **other** `EXECUTED` CGA agreements
        plus this candidate agreement's own requirement, else
        `ERR_RESERVE_DEFICIENT`."

        Design: Difficulty/combinatorial_formula/reserve_gate_evaluation_order_mode_c
        """
        _cga1, cga2 = self._setup_solvent_pool_and_candidate(
            api, gift_admin_headers, estate_manager_headers
        )
        # Gate: 7570148 >= 7570148 (booked) + 0 (other EXECUTED) + 7570148
        # (candidate) is false -> the candidate's own requirement blocks it.
        resp = api.execute_gift_agreement(cga2["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESERVE_DEFICIENT)
        assert resp.status_code == 409

        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["posture"] == "SOLVENT"
        assert pool["booked_coverage_bps"] == 10000

    def test_rejected_candidate_leaves_no_partial_execution(
        self, api, compliance_headers, gift_admin_headers, estate_manager_headers
    ):
        """PRD §3.3: "for `CGA` agreements only, the reserve gate — the fund's
        `balance_cents` must be at least `booked_target_cents` plus the summed
        `reserve_requirement_cents` of all **other** `EXECUTED` CGA agreements
        plus this candidate agreement's own requirement, else
        `ERR_RESERVE_DEFICIENT`."
        A rejected execution never reaches the bookkeeping effects, so the
        candidate stays DRAFT with no booked economics pinned.

        Design: Difficulty/combinatorial_formula/reserve_gate_evaluation_order_mode_c
        """
        _cga1, cga2 = self._setup_solvent_pool_and_candidate(
            api, gift_admin_headers, estate_manager_headers
        )
        resp = api.execute_gift_agreement(cga2["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESERVE_DEFICIENT)
        after = validate_success(api.get_gift_agreement(cga2["id"], gift_admin_headers))
        assert after["status"] == "DRAFT"
        assert after["booked_deduction_cents"] is None


class TestCoverageBoundary:
    def _setup_exact_coverage(self, api, gift_admin_headers, estate_manager_headers):
        donor = make_donor(full_name="Boundary Coverage")
        make_active_rate_table()
        cga = make_funded_cga_with_reserve(donor["id"])
        return cga

    def test_exact_equality_solvent_and_one_cent_below_deficient(
        self, api, compliance_headers, gift_admin_headers, estate_manager_headers
    ):
        """PRD §2.8: "The boundary is inclusive: coverage of exactly 10000
        basis points is solvent, while a balance one cent below target floors
        to 9999 and is deficient."
        PRD §2.6: "The one exception to half-up rounding is the reserve
        coverage ratio `booked_coverage_bps`, which is **floored** to integer
        basis points — a deficient ratio never rounds up into compliance."

        Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_10000_solvent
        """
        self._setup_exact_coverage(api, gift_admin_headers, estate_manager_headers)
        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["balance_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS
        assert pool["booked_target_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS
        assert pool["booked_coverage_bps"] == 10000
        assert pool["posture"] == "SOLVENT"

        drawn = withdraw_reserve(1)
        assert drawn["balance_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS - 1
        assert drawn["booked_coverage_bps"] == 9999
        assert drawn["posture"] == "RESERVE_DEFICIENT"

    def test_one_cent_restoration_returns_to_solvent(
        self, api, compliance_headers, gift_admin_headers, estate_manager_headers
    ):
        """PRD §2.8: "Fourth, `posture` is `SOLVENT` when `booked_target_cents`
        is zero or `booked_coverage_bps` is at least 10000, and
        `RESERVE_DEFICIENT` otherwise. The boundary is inclusive: coverage of
        exactly 10000 basis points is solvent, while a balance one cent below
        target floors to 9999 and is deficient."

        Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_10000_solvent
        """
        self._setup_exact_coverage(api, gift_admin_headers, estate_manager_headers)
        drawn = withdraw_reserve(1)
        assert drawn["posture"] == "RESERVE_DEFICIENT"
        restored = contribute_reserve(1)
        assert restored["balance_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS
        assert restored["booked_coverage_bps"] == 10000
        assert restored["posture"] == "SOLVENT"


class TestAdjustmentSolvency:
    def test_withdrawal_exceeding_balance_rejected(self, api, compliance_headers):
        """PRD §3.9: "A contribution adds the amount to `balance_cents`; a
        withdrawal subtracts it, and the withdrawal amount must not exceed
        `balance_cents`, else `ERR_INSUFFICIENT_RESERVE_BALANCE` (HTTP 422)."

        Design: Corner/validations/withdrawal_exceeding_balance_rejected
        """
        contribute_reserve(500000)
        v1 = reserve_version()
        resp = api.create_reserve_adjustment(
            {
                "direction": "WITHDRAWAL",
                "amount_cents": 500001,
                "expected_reserve_fund_version": v1,
            },
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RESERVE_BALANCE)
        assert resp.status_code == 422
        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["balance_cents"] == 500000
        assert pool["version"] == v1


class TestReserveOcc:
    def test_occ_reserve_adjustment_stale_version_rejected(self, api, compliance_headers):
        """PRD §2.9: "Posting a manual reserve adjustment requires the request
        to carry `expected_reserve_fund_version`, holding the reserve fund
        `version` the client last observed. Adjustments legitimately stack — a
        contribution and a withdrawal both succeed in sequence — so each
        adjustment must be based on the current version; a stale version proves
        the client computed its amount from a superseded balance or coverage
        snapshot. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_reserve_adjustment_stale_version_rejected
        """
        v0 = reserve_version()
        first = validate_success(
            api.create_reserve_adjustment(
                {
                    "direction": "CONTRIBUTION",
                    "amount_cents": 100000,
                    "expected_reserve_fund_version": v0,
                },
                compliance_headers,
            )
        )
        assert first["version"] == v0 + 1
        assert first["balance_cents"] == 100000

        # Replaying against the superseded version is rejected.
        resp = api.create_reserve_adjustment(
            {
                "direction": "CONTRIBUTION",
                "amount_cents": 100000,
                "expected_reserve_fund_version": v0,
            },
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["balance_cents"] == 100000


class TestCompensatingAdjustmentPair:
    def _setup(self, api, gift_admin_headers, estate_manager_headers):
        donor = make_donor(full_name="Invariant Cash")
        make_active_rate_table()
        return make_funded_cga_with_reserve(donor["id"])

    def test_contribution_then_withdrawal_restores_balance(
        self, api, compliance_headers, gift_admin_headers, estate_manager_headers
    ):
        """PRD §3.9: "A contribution adds the amount to `balance_cents`; a
        withdrawal subtracts it, and the withdrawal amount must not exceed
        `balance_cents`, else `ERR_INSUFFICIENT_RESERVE_BALANCE` (HTTP 422).
        Coverage and posture are recomputed after every adjustment, and the
        fund's `version` increments on every balance, target, or posture
        mutation."

        Design: Difficulty/compensating_invariant/reserve_adjustment_contribution_withdrawal_neutral
        """
        self._setup(api, gift_admin_headers, estate_manager_headers)
        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["balance_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS

        up = contribute_reserve(500000)
        assert up["balance_cents"] == STD_CGA_RESERVE_REQUIREMENT_CENTS + 500000
        down = withdraw_reserve(500000)
        # Invariant: the compensating pair is cash-neutral.
        assert down["balance_cents"] == pool["balance_cents"]
        assert down["booked_coverage_bps"] == 10000
        assert down["posture"] == "SOLVENT"

    def test_compensating_pair_advances_version_exactly_twice(
        self, api, compliance_headers, gift_admin_headers, estate_manager_headers
    ):
        """PRD §2.9: "Adjustments legitimately stack — a contribution and a
        withdrawal both succeed in sequence — so each adjustment must be based
        on the current version".
        PRD §3.9: "the fund's `version` increments on every balance, target, or
        posture mutation."

        Design: Difficulty/compensating_invariant/reserve_adjustment_contribution_withdrawal_neutral
        """
        self._setup(api, gift_admin_headers, estate_manager_headers)
        v0 = reserve_version()
        up = contribute_reserve(500000)
        assert up["version"] == v0 + 1
        down = withdraw_reserve(500000)
        assert down["version"] == v0 + 2


class TestNonCgaExcludedFromReserve:
    def test_reserve_target_excludes_non_cga(self, api, compliance_headers):
        """PRD §2.8: "First, `booked_target_cents` is the sum of
        `reserve_requirement_cents` over agreements whose `vehicle_type` is
        `CGA` and whose `status` is one of `FUNDED`, `ACTIVE`, or `SUSPENDED` —
        the statutory basis."
        PRD §3.9: "Non-CGA vehicles always carry a `reserve_requirement_cents`
        of zero."

        Design: Corner/calculations/reserve_target_excludes_non_cga
        """
        donor = make_donor(full_name="Filter Set")
        make_active_rate_table()
        agreement, _payments = make_active_agreement(
            donor["id"], vehicle_type="CRT_ANNUITY", payout_rate_bps=600
        )
        current = validate_success(api.get_gift_agreement(agreement["id"], compliance_headers))
        assert current["status"] == "ACTIVE"
        assert current["reserve_requirement_cents"] == 0

        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["booked_target_cents"] == 0
        assert pool["projected_target_cents"] == 0
        assert pool["booked_coverage_bps"] is None
        assert pool["posture"] == "SOLVENT"
