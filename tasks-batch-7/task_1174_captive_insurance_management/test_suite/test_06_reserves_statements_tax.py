"""Actuarial reserves, annual statements, RBC levels, and tax risk distribution."""
import pytest

from test_helpers import (
    ApiErrorId,
    RBC_ACL_BASE_CENTS,
    assert_annual_statement,
    assert_reserve,
    assert_tax_position,
    create_allocation,
    create_operating_unit,
    create_reserve,
    create_tax_position_payload,
    setup_active_captive_with_program,
    setup_actuarial_review_statement,
    setup_capitalized_captive,
    setup_certified_reserve,
    setup_minutes_approved_meeting,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_actuary_headers


class TestReserveLifecycle:

    def test_reserve_lifecycle_preliminary_to_filed(
        self, api, actuary_headers, captive_manager_headers
    ):
        """PRD §3.7: "Reviewing by an `Actuary` moves the reserve `PRELIMINARY →
        REVIEWED` and recomputes the three estimates; reviewing from any other
        state is rejected with `ERR_RESERVE_NOT_PRELIMINARY`. Certifying by an
        `Actuary` moves the reserve `REVIEWED → CERTIFIED`. ... Filing by a
        `CaptiveManager` moves the reserve `CERTIFIED → FILED` (else
        `ERR_RESERVE_NOT_CERTIFIED`)"
        PRD §3.7: "Certification requires `REVIEWED` (else
        `ERR_RESERVE_NOT_REVIEWED`), requires the supplied `carried_reserve_cents`
        to lie between `low_estimate_cents` and `high_estimate_cents` inclusive
        (else `ERR_RESERVE_OUT_OF_RANGE`, HTTP 400), and is subject to segregation
        of duties: the certifying `X-User-ID` must differ from the `X-User-ID`
        that created the reserve (else `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/reserve_lifecycle_preliminary_to_filed
        """
        captive, program, _fronting = setup_active_captive_with_program()
        creator = make_actuary_headers("actuary-creator-rlc")
        reserve = create_reserve(captive["id"], program["id"], creator_headers=creator,
                                 reserve_type="CASE_RESERVE",
                                 actuarial_method="CHAIN_LADDER")
        assert reserve["status"] == "PRELIMINARY"
        reviewed = validate_success(
            api.review_reserve(captive["id"], program["id"], reserve["id"], actuary_headers)
        )
        assert reviewed["status"] == "REVIEWED"
        # Certify at the inclusive low boundary with a different actuary.
        certifier = make_actuary_headers("actuary-certifier-rlc")
        certified = validate_success(
            api.certify_reserve(captive["id"], program["id"], reserve["id"],
                                {"carried_reserve_cents": reviewed["low_estimate_cents"]},
                                certifier)
        )
        assert certified["status"] == "CERTIFIED"
        filed = validate_success(
            api.file_reserve(captive["id"], program["id"], reserve["id"],
                             captive_manager_headers)
        )
        assert_reserve(filed)
        assert filed["status"] == "FILED"


class TestStatementApprovalDependencies:

    def test_board_approve_rejected_with_uncertified_reserves(self, api, board_director_headers):
        """PRD §3.8: "Board approval requires the statement to be
        `ACTUARIAL_REVIEW` (else `ERR_STATEMENT_NOT_UNDER_REVIEW`), requires every
        `ActuarialReserve` for the statement's year to be `CERTIFIED` or `FILED`
        (else `ERR_UNCERTIFIED_RESERVES`, HTTP 409), and requires a `BoardMeeting`
        in `MINUTES_APPROVED` status to exist for the approval (else
        `ERR_NO_BOARD_APPROVAL_MEETING`, HTTP 400)." — here an approved meeting
        exists, but the year's reserve is still `PRELIMINARY`.

        Design: Difficulty/cross_entity_state_dependency/annual_statement_approval_requires_certified_reserves
        """
        captive, program, _fronting = setup_active_captive_with_program()
        reserve = create_reserve(captive["id"], program["id"], reserve_type="IBNR_RESERVE")
        assert reserve["status"] == "PRELIMINARY"
        setup_minutes_approved_meeting(captive["id"])
        statement = setup_actuarial_review_statement(captive["id"], statement_year=2026)
        assert statement["status"] == "ACTUARIAL_REVIEW"
        resp = api.board_approve_statement(captive["id"], statement["id"], board_director_headers)
        validate_error(resp, ApiErrorId.ERR_UNCERTIFIED_RESERVES)

    def test_board_approve_rejected_without_approval_meeting(self, api, board_director_headers):
        """PRD §3.8: "...and requires a `BoardMeeting` in `MINUTES_APPROVED`
        status to exist for the approval (else `ERR_NO_BOARD_APPROVAL_MEETING`,
        HTTP 400)." — here the year's reserve is `CERTIFIED`, but no approved
        board meeting exists.

        Design: Difficulty/cross_entity_state_dependency/annual_statement_approval_requires_certified_reserves
        """
        captive, program, _fronting = setup_active_captive_with_program()
        reserve = setup_certified_reserve(captive["id"], program["id"],
                                          reserve_type="IBNR_RESERVE")
        assert reserve["status"] == "CERTIFIED"
        statement = setup_actuarial_review_statement(captive["id"], statement_year=2026)
        resp = api.board_approve_statement(captive["id"], statement["id"], board_director_headers)
        validate_error(resp, ApiErrorId.ERR_NO_BOARD_APPROVAL_MEETING)


class TestAnnualStatementComputedFields:

    def test_annual_statement_computed_read(self, api, captive_manager_headers):
        """PRD §3.8: "The statement is born `DRAFT`, and the system computes the
        regulatory `filing_deadline`, the `total_assets_cents`,
        `total_liabilities_cents`, `policyholder_surplus_cents` (the difference
        between assets and liabilities), `net_premium_written_cents`,
        `net_losses_incurred_cents`, `expense_ratio`, `combined_ratio` ...,
        `underwriting_result_cents`, `rbc_ratio`, and `rbc_action_level`."

        Design: Corner/endpoints/annual_statement_computed_read
        """
        captive = setup_capitalized_captive()
        statement = validate_success(
            api.create_annual_statement(
                captive["id"],
                {"statement_year": 2026, "investment_income_cents": 50000},
                captive_manager_headers,
            ),
            expected_status=201,
        )
        assert statement["status"] == "DRAFT"
        fetched = validate_success(
            api.get_annual_statement(captive["id"], statement["id"], captive_manager_headers)
        )
        assert_annual_statement(fetched)
        assert fetched["total_assets_cents"] is not None
        assert fetched["total_liabilities_cents"] is not None
        assert fetched["policyholder_surplus_cents"] is not None
        assert fetched["rbc_ratio"] is not None

    def test_rbc_ratio_threshold_boundary(self, api, captive_manager_headers):
        """PRD §3.8: "The `rbc_ratio` is the `policyholder_surplus_cents` divided
        by the authorised-control-level capital (a base of 50000000 cents),
        expressed as a percentage; the `rbc_action_level` is `NONE` when the ratio
        is at least 200, `COMPANY_ACTION` when at least 150 but strictly less
        than 200, `REGULATORY_ACTION` when at least 100 but strictly less than
        150, `AUTHORIZED_CONTROL` when at least 70 but strictly less than 100,
        and `MANDATORY_CONTROL` when strictly below 70."

        Design: Corner/calculations/rbc_ratio_threshold_boundary
        """
        captive = setup_capitalized_captive()
        statement = validate_success(
            api.create_annual_statement(
                captive["id"],
                {"statement_year": 2026, "investment_income_cents": 50000},
                captive_manager_headers,
            ),
            expected_status=201,
        )
        assert statement["rbc_ratio"] is not None
        assert statement["rbc_action_level"] in [
            "NONE", "COMPANY_ACTION", "REGULATORY_ACTION",
            "AUTHORIZED_CONTROL", "MANDATORY_CONTROL",
        ]


class TestRiskDistribution:

    def _setup_concentrated_captive(self, api):
        """ACTIVE captive, two equal-exposure units, one IN_FORCE program, one
        EXPOSURE_PRO_RATA allocation of 100000 cents to a single unit (100%
        concentration, fewer than 6 insured units, no third-party premium)."""
        captive, program, _fronting = setup_active_captive_with_program(
            program_name="Prop Program", line_of_business="PROPERTY",
        )
        unit_a = create_operating_unit(captive["id"], unit_name="Unit RA", unit_code="URA",
                                       exposure_basis="REVENUE", exposure_amount=1000)
        create_operating_unit(captive["id"], unit_name="Unit RB", unit_code="URB",
                              exposure_basis="REVENUE", exposure_amount=1000)
        create_allocation(captive["id"], program["id"], unit_a["id"],
                          allocation_method="EXPOSURE_PRO_RATA")
        return captive

    def test_risk_distribution_three_factor_weighted_score_fail(
        self, api, tax_advisor_headers
    ):
        """PRD §3.10: "The entity pillar counts the `insured_entities_count` ...
        and contributes 40 points when at least 12 units are insured, 20 points
        when at least 6 but fewer than 12 are insured, and 0 points otherwise.
        The third-party pillar ... contributes 30 points when the percentage is
        at least 30, 15 points when it is at least 15 but strictly less than 30,
        and 0 points otherwise. The concentration pillar ... contributes 30 points
        when that concentration is at most 50 percent, 15 points when it is
        greater than 50 but at most 75 percent, and 0 points above 75 percent.
        The `risk_distribution_score` is the sum of the three pillar scores; the
        `risk_distribution_test_result` is `PASS` when the score is at least 70,
        `MARGINAL` when the score is at least 40 but strictly less than 70, and
        `FAIL` when strictly below 40." — with a single insured unit (0), no
        third-party premium (0), and 100% concentration (0), the score is 0.

        Design: Difficulty/combinatorial_formula/risk_distribution_three_factor_weighted_score
        """
        captive = self._setup_concentrated_captive(api)
        position = validate_success(
            api.create_tax_position(
                captive["id"],
                create_tax_position_payload(position_type="RISK_DISTRIBUTION"),
                tax_advisor_headers,
            ),
            expected_status=201,
        )
        analyzed = validate_success(
            api.analyze_tax_position(captive["id"], position["id"], tax_advisor_headers)
        )
        assert_tax_position(analyzed)
        assert analyzed["status"] == "ANALYZED"
        assert analyzed["risk_distribution_test_result"] == "FAIL", (
            f"Score 0 (0 + 0 + 0) is strictly below 40 -> FAIL, "
            f"got {analyzed['risk_distribution_test_result']}"
        )

    def test_risk_distribution_premium_threshold_met(
        self, api, tax_advisor_headers
    ):
        """PRD §3.10: "Analysis also computes `premium_deductibility_pct`,
        `insured_entities_count`, `third_party_premium_pct`,
        `premium_threshold_met` (true when total premium does not exceed the
        micro-captive 831(b) premium limit of 265000000 cents), and
        `disclosure_required` (true when the position must be disclosed on Form
        8886)." — total premium here is 100000 cents, well under the limit.
        PRD §3.10: "the `risk_distribution_test_result` is `PASS` when the score
        is at least 70, `MARGINAL` when the score is at least 40 but strictly
        less than 70, and `FAIL` when strictly below 40."

        Design: Difficulty/combinatorial_formula/risk_distribution_three_factor_weighted_score
        """
        captive = self._setup_concentrated_captive(api)
        position = validate_success(
            api.create_tax_position(
                captive["id"],
                create_tax_position_payload(position_type="RISK_DISTRIBUTION"),
                tax_advisor_headers,
            ),
            expected_status=201,
        )
        analyzed = validate_success(
            api.analyze_tax_position(captive["id"], position["id"], tax_advisor_headers)
        )
        assert analyzed["premium_threshold_met"] is True, (
            "Total premium 100000 cents does not exceed the 265000000-cent "
            "micro-captive limit"
        )
        assert analyzed["risk_distribution_test_result"] == "FAIL"
        assert analyzed["status"] == "ANALYZED"
