"""
Boundaries evaluated to the last unit: the examination tolerance's strict
inequality, and an allocation run over an empty allowed set.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import REGULATOR_HEADERS


class TestExaminationToleranceEquality:
    @pytest.fixture
    def two_draft_reports(self, api, base_full):
        """Two adjacent, non-overlapping reporting periods on the base facility."""
        headers = base_full["operator_headers"]
        equal_case = get_success_data(
            api.create_position_report(
                f.position_report_payload(
                    base_full["warehouse_id"],
                    period_start_date="2026-08-01",
                    period_end_date="2026-08-10",
                    as_of_date="2026-08-05",
                ),
                headers,
            ),
            201,
        )
        greater_case = get_success_data(
            api.create_position_report(
                f.position_report_payload(
                    base_full["warehouse_id"],
                    period_start_date="2026-08-11",
                    period_end_date="2026-08-20",
                    as_of_date="2026-08-15",
                ),
                headers,
            ),
            201,
        )
        return {"equal_id": equal_case["id"], "greater_id": greater_case["id"]}

    def test_a_discrepancy_exactly_equal_to_the_tolerance_accepts_without_examination(
        self, api, base_full, two_draft_reports
    ):
        """
        On a 949-bushel obligation the tolerance is the 500-bushel floor, since
        50 basis points of 949 rounds to 5. A declared 449 physical bushels is a
        count discrepancy of exactly -500, which is not strictly greater than the
        tolerance, so the report goes straight to ACCEPTED with a PASS nobody
        examined, and the posture stays OPEN.

        PRD: "`examination_required` is true when the absolute value of **any**
        of the three deltas is **strictly greater** than that tolerance; a delta
        exactly equal to the tolerance does not require examination."

        Design: Difficulty/boundary_precision_check/examination_tolerance_exact_equality_does_not_require_examination
        """
        report = get_success_data(
            api.submit_position_report(
                two_draft_reports["equal_id"],
                f.submit_report_payload(449, 949),
                base_full["operator_headers"],
            ),
            200,
        )

        assert_fields_equal(
            report,
            {
                "examination_tolerance_bushels": 500,
                "count_discrepancy_bushels": -500,
                "obligation_misstatement_bushels": 0,
                "position_variance_bushels": 0,
                "examination_required": False,
                "report_state": "ACCEPTED",
                "examination_result": "PASS",
                "examined_by_user_id": None,
            },
        )

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], REGULATOR_HEADERS), 200
        )
        assert warehouse["operational_posture"] == "OPEN"

    def test_one_bushel_past_the_tolerance_refers_the_report_for_examination(
        self, api, base_full, two_draft_reports
    ):
        """
        The adjacent period declared at 448 physical bushels is a -501
        discrepancy, one bushel past the same 500-bushel tolerance, which routes
        the report to UNDER_EXAMINATION instead of accepting it.

        PRD: "When `examination_required` computes true, a `DRAFT` report goes to
        `UNDER_EXAMINATION` instead, and this branch additionally requires that
        no other report of the same warehouse already sit in
        `UNDER_EXAMINATION`; a second referral while another remains under
        examination is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/examination_tolerance_exact_equality_does_not_require_examination
        """
        get_success_data(
            api.submit_position_report(
                two_draft_reports["equal_id"],
                f.submit_report_payload(449, 949),
                base_full["operator_headers"],
            ),
            200,
        )

        report = get_success_data(
            api.submit_position_report(
                two_draft_reports["greater_id"],
                f.submit_report_payload(448, 949),
                base_full["operator_headers"],
            ),
            200,
        )

        assert_fields_equal(
            report,
            {
                "count_discrepancy_bushels": -501,
                "examination_required": True,
                "report_state": "UNDER_EXAMINATION",
            },
        )


class TestIndemnityAllocationWithNoAllowedClaims:
    @pytest.fixture
    def disallowed_only_proceeding(
        self, api, base_full, claims_open_warehouse, filed_claim
    ):
        """A proceeding whose single claim has been disallowed before allocation."""
        claims_open_warehouse(base_full["warehouse_id"])
        claim = filed_claim(
            base_full["warehouse_id"],
            base_full["receipt_id"],
            base_full["depositor_id"],
            1000000,
        )
        get_success_data(
            api.adjudicate_indemnity_claim(
                claim["id"],
                f.adjudicate_payload(
                    "DISALLOW", adjudication_note="receipt already satisfied"
                ),
                REGULATOR_HEADERS,
            ),
            200,
        )
        return claim["id"]

    def test_allocation_over_an_empty_allowed_set_advances_with_zero_roll_ups(
        self, api, base_full, disallowed_only_proceeding
    ):
        """
        No claim remains FILED, so the run is admissible; no claim is ALLOWED, so
        the pro-rata base is empty and every roll-up the run materialises reads
        exactly zero while the proceeding advances to ALLOCATED.

        PRD: "The run operates over the warehouse's claims in `claim_state`
        `ALLOWED` only; disallowed claims are excluded from the pro-rata base
        entirely."

        Design: Difficulty/boundary_precision_check/indemnity_allocation_with_zero_allowed_claims
        """
        warehouse = get_success_data(
            api.insolvency_action(
                base_full["warehouse_id"],
                f.insolvency_payload("ALLOCATE"),
                REGULATOR_HEADERS,
            ),
            200,
        )

        assert_fields_equal(
            warehouse,
            {
                "insolvency_state": "ALLOCATED",
                "allowed_claim_total_cents": 0,
                "bond_allocated_cents": 0,
                "fund_allocated_cents": 0,
                "allocated_total_cents": 0,
                "unpaid_claim_total_cents": 0,
            },
        )

    def test_the_disallowed_claim_stays_disallowed_and_draws_nothing(
        self, api, base_full, disallowed_only_proceeding
    ):
        """
        The allocation run moves only allowed claims to SETTLED, so the
        disallowed claim keeps its own state and all four money figures at zero.

        PRD: "`DISALLOW` moves the claim to `DISALLOWED` and leaves
        `allowed_cents` at zero, so the claim draws nothing from either tier of
        the waterfall and contributes nothing to the pro-rata base."

        Design: Difficulty/boundary_precision_check/indemnity_allocation_with_zero_allowed_claims
        """
        get_success_data(
            api.insolvency_action(
                base_full["warehouse_id"],
                f.insolvency_payload("ALLOCATE"),
                REGULATOR_HEADERS,
            ),
            200,
        )

        claim = get_success_data(
            api.get_indemnity_claim(disallowed_only_proceeding, REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            claim,
            {
                "claim_state": "DISALLOWED",
                "allowed_cents": 0,
                "bond_share_cents": 0,
                "fund_share_cents": 0,
                "unpaid_cents": 0,
            },
        )
