"""Bond proposals and the project list: debt capacity, site construction
windows, priority ranks, and aggregate caps (PRD §3.6)."""
from test_helpers import (
    ApiErrorId, assert_bond_proposal, get_success_data, validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_bond_project_payload, create_bond_proposal_payload,
)
from test_helpers.fixtures import (
    add_project, approve_board, create_bond_proposal, create_open_fiscal_year,
)
from test_helpers.test_users import TEST_USERS

BC = TEST_USERS["board_clerk_headers"]
AU = TEST_USERS["auditor_headers"]


class TestBondCapacity:
    def _capacity_scenario(self):
        """OPEN year (outstanding 4,500,000; EAV 500,000,000; limit
        34,500,000) + proposal A 18,000,000 BOARD_APPROVED + proposals B
        (12,000,000) and C (0.01) in DRAFT with their project lists."""
        fy = create_open_fiscal_year()
        bp_a = create_bond_proposal(fy["id"], total_amount=18000000)
        add_project(bp_a["id"], "Roof Replacement", "HS-01", 18000000,
                    "2028-06-01", "2028-12-15", 1)
        approve_board(bp_a["id"])
        bp_b = create_bond_proposal(fy["id"], total_amount=12000000,
                                    question_title="Bond Question B",
                                    purpose="HVAC")
        add_project(bp_b["id"], "HVAC Replacement", "ES-02", 12000000,
                    "2028-06-01", "2028-11-30", 1)
        bp_c = create_bond_proposal(fy["id"], total_amount=0.01,
                                    question_title="Bond Question C",
                                    purpose="Contingency")
        add_project(bp_c["id"], "Contingency", "MS-03", 0.01,
                    "2028-06-01", "2028-07-01", 1)
        return fy, bp_a, bp_b, bp_c

    def test_capacity_exactly_at_legal_limit_allowed(self, api):
        """PRD §3.6: "the year's `outstanding_debt_principal`, plus the summed
        `remaining_authorization` of the fiscal year's *other* proposals in
        `BOARD_APPROVED`, `REFERRED`, or `PASSED` status (proposals in `DRAFT`
        or `FAILED` consume nothing), plus this proposal's `total_amount`, may
        not exceed 6.9 percent of the year's `eav_current`. Landing exactly on
        the limit is permitted; exceeding it fails with
        `ERR_BOND_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/bond_capacity_exactly_at_legal_limit_allowed_one_cent_over_rejected
        """
        _, _, bp_b, _ = self._capacity_scenario()
        # 4,500,000 + 18,000,000 + 12,000,000 == 34,500,000 == 6.9% of EAV.
        data = validate_success(api.approve_bond_proposal_board(bp_b["id"],
                                                                BC), 200)
        assert data["status"] == "BOARD_APPROVED"

    def test_one_cent_over_legal_limit_rejected(self, api):
        """PRD §3.6: "Landing exactly on the limit is permitted; exceeding it
        fails with `ERR_BOND_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/bond_capacity_exactly_at_legal_limit_allowed_one_cent_over_rejected
        """
        _, _, bp_b, bp_c = self._capacity_scenario()
        approve_board(bp_b["id"])  # capacity now exactly exhausted
        resp = api.approve_bond_proposal_board(bp_c["id"], BC)
        validate_error(resp, ApiErrorId.ERR_BOND_CAPACITY_EXCEEDED, 422)
        bp_c_now = validate_success(api.get_bond_proposal(bp_c["id"], AU), 200)
        assert bp_c_now["status"] == "DRAFT"


class TestSiteWindows:
    def test_overlap_short_gap_and_touching_rejected(self, api):
        """PRD §3.6: "The new project conflicts when its window overlaps the
        other's window, or when the whole-day gap separating the two windows
        is strictly less than 14 days; either condition rejects the create
        with `ERR_SITE_WINDOW_CONFLICT`. A gap of exactly 14 days is
        permitted, while windows that merely touch — one's end day equal to
        the other's start day — have a gap of zero and are rejected, the
        buffer dominating the adjacency."

        Design: Difficulty/resource_temporal_overlap/site_window_half_open_overlap_with_fourteen_day_buffer
        """
        fy = create_open_fiscal_year()
        bp = create_bond_proposal(fy["id"], total_amount=18000000)
        add_project(bp["id"], "Roof Replacement", "HS-01", 6000000,
                    "2028-06-01", "2028-08-15", 1)
        # Gap of 5 days (2028-08-15 -> 2028-08-20) < 14: conflict.
        resp = api.create_bond_project(bp["id"], create_bond_project_payload(
            "Early Start", "HS-01", 1000000, "2028-08-20", "2028-09-30", 2),
            BC)
        validate_error(resp, ApiErrorId.ERR_SITE_WINDOW_CONFLICT, 409)
        # True overlap (2028-08-10 < 2028-08-15): conflict.
        resp = api.create_bond_project(bp["id"], create_bond_project_payload(
            "Overlapping", "HS-01", 1000000, "2028-08-10", "2028-09-30", 3),
            BC)
        validate_error(resp, ApiErrorId.ERR_SITE_WINDOW_CONFLICT, 409)
        # Touching windows (start == other's end): gap 0, rejected.
        resp = api.create_bond_project(bp["id"], create_bond_project_payload(
            "Touching", "HS-01", 1000000, "2028-08-15", "2028-09-15", 4), BC)
        validate_error(resp, ApiErrorId.ERR_SITE_WINDOW_CONFLICT, 409)

    def test_exact_buffer_and_other_site_allowed(self, api):
        """PRD §3.6: "A gap of exactly 14 days is permitted" and "a new
        project is checked against every other project sharing its `site_code`
        that is in `PLANNED`, `AUTHORIZED`, or `IN_PROGRESS` (cancelled and
        completed projects are ignored)" — the conflict set is per site_code.

        Design: Difficulty/resource_temporal_overlap/site_window_half_open_overlap_with_fourteen_day_buffer
        """
        fy = create_open_fiscal_year()
        bp = create_bond_proposal(fy["id"], total_amount=18000000)
        add_project(bp["id"], "Roof Replacement", "HS-01", 6000000,
                    "2028-06-01", "2028-08-15", 1)
        # Gap of exactly 14 days (2028-08-15 -> 2028-08-29): allowed.
        ok = add_project(bp["id"], "Exact Buffer", "HS-01", 1000000,
                         "2028-08-29", "2028-10-15", 2)
        assert ok["status"] == "PLANNED"
        # Identical window on a DIFFERENT site: allowed.
        other = add_project(bp["id"], "Other Site Same Window", "ES-02",
                            1000000, "2028-06-01", "2028-08-15", 3)
        assert other["status"] == "PLANNED"


class TestProjectListRules:
    def test_duplicate_priority_rank_rejected(self, api):
        """PRD §3.6: "a `priority_rank` unique among the proposal's
        non-`CANCELLED` projects — a reused rank fails with
        `ERR_DUPLICATE_PRIORITY_RANK`."

        Design: Corner/validations/duplicate_priority_rank_rejected
        """
        fy = create_open_fiscal_year()
        bp = create_bond_proposal(fy["id"], total_amount=18000000)
        add_project(bp["id"], "Roof Replacement", "HS-01", 6000000,
                    "2028-06-01", "2028-08-15", 1)
        resp = api.create_bond_project(bp["id"], create_bond_project_payload(
            "Gym Renovation", "ES-02", 7000000, "2028-06-01", "2028-12-15",
            1), BC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRIORITY_RANK, 409)

    def test_project_list_sum_equals_amount_allowed_then_over_rejected(
            self, api):
        """PRD §3.6: "The summed `estimated_cost` over the proposal's
        non-`CANCELLED` projects may never exceed the proposal's
        `total_amount`; an addition that would push the list over fails with
        `ERR_PROJECT_LIST_EXCEEDS_AMOUNT`."

        Design: Corner/calculations/project_list_sum_equals_amount_allowed_then_over_rejected
        """
        fy = create_open_fiscal_year()
        bp = create_bond_proposal(fy["id"], total_amount=18000000)
        add_project(bp["id"], "Roof Replacement", "HS-01", 10000000,
                    "2028-06-01", "2028-08-15", 1)
        # 10,000,000 + 8,000,000 == 18,000,000 total exactly: allowed.
        add_project(bp["id"], "Gym Renovation", "ES-02", 8000000,
                    "2028-06-01", "2028-12-15", 2)
        # A further 0.01 crosses the total: rejected.
        resp = api.create_bond_project(bp["id"], create_bond_project_payload(
            "Contingency", "MS-03", 0.01, "2028-06-01", "2028-07-01", 3), BC)
        validate_error(resp, ApiErrorId.ERR_PROJECT_LIST_EXCEEDS_AMOUNT, 422)

    def test_approve_proposal_with_empty_project_list_rejected(self, api):
        """PRD §3.6: "Approval requires at least one project of the proposal
        still in `PLANNED` status — an empty list fails with
        `ERR_EMPTY_PROJECT_LIST`".

        Design: Corner/validations/approve_proposal_with_empty_project_list_rejected
        """
        fy = create_open_fiscal_year()
        bp = create_bond_proposal(fy["id"], total_amount=18000000)
        resp = api.approve_bond_proposal_board(bp["id"], BC)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PROJECT_LIST, 409)
        bp_now = validate_success(api.get_bond_proposal(bp["id"], AU), 200)
        assert bp_now["status"] == "DRAFT"
