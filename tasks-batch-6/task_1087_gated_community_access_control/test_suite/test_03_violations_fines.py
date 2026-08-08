"""Violations and fines: tiered assessment, per-line late-fee rounding, the
cyclic appeal/withdraw loop, balance conservation, delinquency boundary, and the
segregation-of-duties / payment / statement guards.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_community, create_resident, issue_violation, appeal_violation,
    setup_community_and_resident,
    make_admin_headers, make_resident_headers,
    ADMIN, OFFICER,
)


class TestViolationTieredFine:
    """Tests for the violation_fine_tiered_multiplier rule (see per-test Design tags)."""

    def _setup_prior_speeding(self):
        community, resident = setup_community_and_resident(resident_overrides={"full_name": "Sam Speeder"})
        issue_violation(community["id"], resident["id"], violation_type="SPEEDING", base_fine_cents=10000)
        return community, resident

    def test_second_same_type_violation_applies_tier_1_5(self, api):
        """PRD §3.7: "The tier multiplier is 1.0 when `repeat_index` is 0, 1.5
        when it is 1, 2.0 when it is 2, and 3.0 when it is 3 or more. The base
        component is `base_fine_cents` multiplied by the tier multiplier, rounded
        half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/violation_fine_tiered_multiplier
        """
        community, resident = self._setup_prior_speeding()
        v2 = issue_violation(community["id"], resident["id"],
                             violation_type="SPEEDING", base_fine_cents=10000)
        assert v2["assessed_fine_cents"] == 15000, "10000 * 1.5 tier"

    def test_repeat_index_counts_prior_same_type(self, api):
        """PRD §3.7: "First the system computes `repeat_index`: the count of the
        same resident's other violations of the same `violation_type` whose
        `status` is `ISSUED`, `UPHELD`, `REDUCED`, or `PAID` and whose own
        `issued_at` falls within the 180-day repeat window ending at this
        issuance".

        Design: Difficulty/combinatorial_formula/violation_fine_tiered_multiplier
        """
        community, resident = self._setup_prior_speeding()
        v2 = issue_violation(community["id"], resident["id"],
                             violation_type="SPEEDING", base_fine_cents=10000)
        assert v2["repeat_index"] == 1


class TestLateFeePerLineRounding:
    """Tests for the late_fee_per_line_rounding_order rule (see per-test Design tags)."""

    def _setup_two_open_violations(self):
        community, resident = setup_community_and_resident(resident_overrides={"resident_type": "TENANT"})
        issue_violation(community["id"], resident["id"], violation_type="NOISE", base_fine_cents=10033)
        issue_violation(community["id"], resident["id"], violation_type="PARKING", base_fine_cents=15077)
        return community, resident

    def test_late_fee_rounded_per_line_then_summed(self, api):
        """PRD §3.8: "for each of the resident's violations whose `status` is
        `ISSUED`, `UPHELD`, or `REDUCED`, the system multiplies that violation's
        `assessed_fine_cents` by the late-fee rate of 1.5 percent (0.015) and
        rounds the result half-up to a whole cent, and `accrued_late_fee_cents`
        is the sum of those per-line rounded amounts — the rounding is applied to
        each line before summation, never to a single combined total."

        Design: Difficulty/combinatorial_formula/late_fee_per_line_rounding_order
        """
        community, resident = self._setup_two_open_violations()
        stmt = validate_success(api.get_resident_statement(resident["id"], ADMIN))
        # round(150.495)+round(226.155) = 150 + 226 = 376
        assert stmt["accrued_late_fee_cents"] == 376

    def test_late_fee_is_not_sum_then_round(self, api):
        """PRD §3.8: "the rounding is applied to each line before summation, never
        to a single combined total."

        Design: Difficulty/combinatorial_formula/late_fee_per_line_rounding_order
        """
        community, resident = self._setup_two_open_violations()
        stmt = validate_success(api.get_resident_statement(resident["id"], ADMIN))
        assert stmt["accrued_late_fee_cents"] != 377, "sum-then-round would give 377"


class TestViolationCyclicAppeal:
    """Tests for the violation_cyclic_appeal_withdraw_loop rule (see per-test Design tags)."""

    def _issued_violation(self):
        community, resident = setup_community_and_resident()
        v = issue_violation(community["id"], resident["id"],
                            violation_type="PARKING", base_fine_cents=8000)
        return community, resident, v

    def test_appeal_moves_to_appealed(self, api):
        """PRD §3.7: "A cited resident may appeal an `ISSUED` violation, moving
        its `status` to `APPEALED`, and may withdraw that appeal to return it from
        `APPEALED` to `ISSUED` — a revision loop that may repeat before
        resolution."

        Design: Difficulty/non_linear_state_machine/violation_cyclic_appeal_withdraw_loop
        """
        _, resident, v = self._issued_violation()
        appealed = validate_success(
            api.appeal_violation(v["id"], {"reason": "Was parked legally"},
                                 make_resident_headers(resident["id"])))
        assert appealed["status"] == "APPEALED"

    def test_withdraw_appeal_returns_to_issued(self, api):
        """PRD §3.7: "A cited resident may appeal an `ISSUED` violation, moving
        its `status` to `APPEALED`, and may withdraw that appeal to return it from
        `APPEALED` to `ISSUED` — a revision loop that may repeat before
        resolution."

        Design: Difficulty/non_linear_state_machine/violation_cyclic_appeal_withdraw_loop
        """
        _, resident, v = self._issued_violation()
        appeal_violation(v["id"], resident["id"], reason="Was parked legally")
        looped = validate_success(
            api.withdraw_appeal_violation(v["id"], make_resident_headers(resident["id"])))
        assert looped["status"] == "ISSUED"


class TestBalanceConservationDismiss:
    """Tests for the resident_balance_conservation_issue_then_dismiss rule (see per-test Design tags)."""

    def _issue_appeal_dismiss(self, api):
        community, resident = setup_community_and_resident()
        v = issue_violation(community["id"], resident["id"],
                            violation_type="NOISE", base_fine_cents=12000)
        appeal_violation(v["id"], resident["id"])
        resolved = validate_success(
            api.resolve_violation(v["id"], {"resolution": "DISMISSED"}, make_admin_headers("admin-9")))
        return community, resident, v, resolved

    def test_dismiss_reverses_balance_to_zero(self, api):
        """PRD §3.7: "A `resolution` of `DISMISSED` moves `status` to the terminal
        `DISMISSED` and removes the fine from the balance — the resident's
        `outstanding_balance_cents` decreases by that violation's
        `assessed_fine_cents` as a compensating reversal of issuance — then
        recomputes standing."

        Design: Difficulty/compensating_invariant/resident_balance_conservation_issue_then_dismiss
        """
        _, resident, _, resolved = self._issue_appeal_dismiss(api)
        assert resolved["status"] == "DISMISSED"
        r = validate_success(api.get_resident(resident["id"], ADMIN))
        assert r["outstanding_balance_cents"] == 0

    def test_dismiss_returns_standing_to_good(self, api):
        """PRD §3.7: "the resident's `outstanding_balance_cents` decreases by that
        violation's `assessed_fine_cents` as a compensating reversal of issuance
        — then recomputes standing."

        Design: Difficulty/compensating_invariant/resident_balance_conservation_issue_then_dismiss
        """
        _, resident, _, _ = self._issue_appeal_dismiss(api)
        r = validate_success(api.get_resident(resident["id"], ADMIN))
        assert r["standing"] == "GOOD"


class TestDelinquencyBoundary:
    """Tests for the delinquency_threshold_inclusive_boundary rule (see per-test Design tags)."""

    def test_balance_at_threshold_is_delinquent(self, api):
        """PRD §3.1: "The resident's `standing` is `DELINQUENT` when
        `outstanding_balance_cents` is greater than or equal to the delinquency
        threshold of 25,000 cents, and `GOOD` otherwise — the boundary is
        inclusive, so a balance of exactly 25,000 cents is `DELINQUENT`."

        Design: Difficulty/boundary_precision_check/delinquency_threshold_inclusive_boundary
        """
        community, resident = setup_community_and_resident(resident_overrides={"full_name": "Ann AtThreshold"})
        issue_violation(community["id"], resident["id"],
                        violation_type="PARKING", base_fine_cents=25000)
        r = validate_success(api.get_resident(resident["id"], ADMIN))
        assert r["outstanding_balance_cents"] == 25000
        assert r["standing"] == "DELINQUENT"

    def test_balance_below_threshold_is_good(self, api):
        """PRD §3.1: "The resident's `standing` is `DELINQUENT` when
        `outstanding_balance_cents` is greater than or equal to the delinquency
        threshold of 25,000 cents, and `GOOD` otherwise — the boundary is
        inclusive, so a balance of exactly 25,000 cents is `DELINQUENT`."

        Design: Difficulty/boundary_precision_check/delinquency_threshold_inclusive_boundary
        """
        community, resident = setup_community_and_resident(resident_overrides={"full_name": "Ben BelowThreshold"})
        issue_violation(community["id"], resident["id"],
                        violation_type="PARKING", base_fine_cents=24999)
        r = validate_success(api.get_resident(resident["id"], ADMIN))
        assert r["outstanding_balance_cents"] == 24999
        assert r["standing"] == "GOOD"


def test_resolve_by_issuer_returns_segregation_of_duties(api):
    """PRD §3.7: "Every resolution is subject to segregation of duties: the acting
    `X-User-ID` must differ from the violation's `issued_by_user_id`, and a
    resolver who issued the violation is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/resolve_by_issuer_returns_segregation_of_duties
    """
    community, resident = setup_community_and_resident()
    v = issue_violation(community["id"], resident["id"], issuer_id="off-1",
                        violation_type="SPEEDING", base_fine_cents=9000)
    appeal_violation(v["id"], resident["id"])
    # Resolver X-User-ID == issuer id "off-1" -> SoD.
    validate_error(api.resolve_violation(v["id"], {"resolution": "UPHELD"}, make_admin_headers("off-1")),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)


def test_pay_wrong_amount_returns_invalid_resolution(api):
    """PRD §3.7: "The payment must exactly equal the current
    `assessed_fine_cents`; any other amount is refused with
    `ERR_INVALID_RESOLUTION`."

    Design: Corner/validations/pay_wrong_amount_returns_invalid_resolution
    """
    community, resident = setup_community_and_resident()
    v = issue_violation(community["id"], resident["id"],
                        violation_type="PARKING", base_fine_cents=5000)
    validate_error(api.pay_violation(v["id"], {"amount_cents": 4000},
                                     make_resident_headers(resident["id"])),
                   ApiErrorId.ERR_INVALID_RESOLUTION.value)


def test_withdraw_appeal_from_issued_returns_invalid_state(api):
    """PRD §3.7: "A cited resident may appeal an `ISSUED` violation, moving its
    `status` to `APPEALED`, and may withdraw that appeal to return it from
    `APPEALED` to `ISSUED` — a revision loop that may repeat before resolution."

    Design: Corner/state_machines/withdraw_appeal_from_issued_returns_invalid_state
    """
    community, resident = setup_community_and_resident()
    v = issue_violation(community["id"], resident["id"],
                        violation_type="PARKING", base_fine_cents=5000)
    validate_error(api.withdraw_appeal_violation(v["id"], make_resident_headers(resident["id"])),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_violation_issue_immediately_visible_on_statement(api):
    """PRD §3.1: "The `outstanding_balance_cents` is the sum of
    `assessed_fine_cents` across the resident's violations whose `status` is
    `ISSUED`, `APPEALED`, `UPHELD`, or `REDUCED`, minus the sum of
    `paid_amount_cents` across the resident's violations whose `status` is
    `PAID`."

    Design: Corner/consistency_model/violation_issue_immediately_visible_on_statement
    """
    community, resident = setup_community_and_resident()
    issue_violation(community["id"], resident["id"],
                    violation_type="NOISE", base_fine_cents=8000)
    stmt = validate_success(api.get_resident_statement(resident["id"], ADMIN))
    assert stmt["outstanding_balance_cents"] == 8000


def test_violations_summary_report_aggregates(api):
    """PRD §3.8: "The violations-summary report returns `open_count`, the number
    of the community's violations still counted in residents' balances (`status`
    of `ISSUED`, `APPEALED`, `UPHELD`, or `REDUCED`); `total_assessed_cents`, the
    sum of `assessed_fine_cents` across those same violations".

    Design: Corner/endpoints/violations_summary_report_aggregates
    """
    community, resident = setup_community_and_resident()
    issue_violation(community["id"], resident["id"],
                    violation_type="NOISE", base_fine_cents=6000)
    report = validate_success(api.get_violations_summary_report(community["id"], ADMIN))
    assert report["open_count"] == 1
    assert report["total_assessed_cents"] == 6000
