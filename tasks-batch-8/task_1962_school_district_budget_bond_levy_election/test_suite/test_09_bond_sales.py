"""Bond sales: the PASSED gate, remaining authorization, net proceeds, the
authorization window, close timing, and OCC on the proposal (PRD §2.8,
§3.8)."""
from test_helpers import (
    ApiErrorId, assert_money, get_success_data, validate_error,
    validate_paginated, validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_bond_sale_payload
from test_helpers.fixtures import (
    approve_board, close_sale, create_bond_sale, get_bond_proposal, set_clock,
    setup_approved_proposal, setup_closed_sale, setup_passed_proposal,
)
from test_helpers.test_users import TEST_USERS

BC = TEST_USERS["board_clerk_headers"]
DT = TEST_USERS["district_treasurer_headers"]
AU = TEST_USERS["auditor_headers"]

ONE_PROJECT = [("Roof Replacement", "HS-01", 6000000, "2028-06-01",
                "2028-08-15")]


class TestSaleStateGate:
    def test_sale_create_rejected_before_proposal_passes(self, api):
        """PRD §3.8: "Once a proposal has `PASSED`, the `DistrictTreasurer`
        may plan a **bond sale** series against it — a proposal in any other
        status rejects the create with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/bond_sale_gated_by_proposal_passed
        """
        ctx = setup_approved_proposal(projects=ONE_PROJECT)  # BOARD_APPROVED
        bp = get_bond_proposal(ctx["bp"]["id"])
        resp = api.create_bond_sale(
            ctx["bp"]["id"],
            create_bond_sale_payload(
                "2027-A", 10000000, 150000, 80000, "2027-12-01",
                expected_bond_proposal_version=bp["version"]),
            DT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_sale_create_succeeds_after_proposal_passes(self, api):
        """PRD §3.8: "Once a proposal has `PASSED`, the `DistrictTreasurer`
        may plan a **bond sale** series against it" and "The economics must
        also be real: `net_proceeds`, computed at creation as the `par_amount`
        plus the `premium` minus the `issuance_costs`".

        Design: Difficulty/cross_entity_state_dependency/bond_sale_gated_by_proposal_passed
        """
        ctx = setup_passed_proposal(projects=ONE_PROJECT)
        bp = get_bond_proposal(ctx["bp"]["id"])
        sale = validate_success(api.create_bond_sale(
            ctx["bp"]["id"],
            create_bond_sale_payload(
                "2027-A", 10000000, 150000, 80000, "2027-12-01",
                expected_bond_proposal_version=bp["version"]),
            DT), 201)
        assert sale["status"] == "PLANNED"
        # net_proceeds = 10,000,000 + 150,000 - 80,000
        assert_money(sale["net_proceeds"], 10070000.00, "net_proceeds")


class TestRemainingAuthorization:
    def test_sale_remaining_authorization_exact_boundary(self, api):
        """PRD §3.8: "The `par_amount` may not exceed the proposal's
        `remaining_authorization` — the `total_amount` less the summed
        `par_amount` over the proposal's sales in `PLANNED` or `CLOSED`
        status, with cancelled sales releasing their reservation — and selling
        for exactly the remaining authorization is permitted while anything
        more fails with `ERR_SALE_EXCEEDS_REMAINING_AUTHORIZATION`."

        Design: Corner/calculations/sale_remaining_authorization_exact_boundary
        """
        ctx = setup_passed_proposal()  # total 18,000,000
        bp_id = ctx["bp"]["id"]
        create_bond_sale(bp_id, "2027-A", 10000000, 0, 0, "2027-12-01")
        bp = get_bond_proposal(bp_id)
        # A PLANNED sale consumes authorization: 18M - 10M = 8M remaining.
        assert_money(bp["remaining_authorization"], 8000000.00,
                     "remaining_authorization after planned sale")
        # Selling exactly the remaining 8,000,000 is permitted.
        create_bond_sale(bp_id, "2027-B", 8000000, 0, 0, "2028-01-15")
        bp = get_bond_proposal(bp_id)
        assert_money(bp["remaining_authorization"], 0.00,
                     "remaining_authorization exhausted")
        # One cent over is rejected.
        resp = api.create_bond_sale(
            bp_id,
            create_bond_sale_payload(
                "2027-C", 0.01, 0, 0, "2028-02-01",
                expected_bond_proposal_version=bp["version"]),
            DT)
        validate_error(resp,
                       ApiErrorId.ERR_SALE_EXCEEDS_REMAINING_AUTHORIZATION,
                       422)


class TestSaleEconomics:
    def test_nonpositive_net_proceeds_rejected(self, api):
        """PRD §3.8: "The economics must also be real: `net_proceeds`,
        computed at creation as the `par_amount` plus the `premium` minus the
        `issuance_costs`, must be greater than zero, and a non-positive result
        fails with `ERR_NONPOSITIVE_NET_PROCEEDS`."

        Design: Corner/calculations/nonpositive_net_proceeds_rejected
        """
        ctx = setup_passed_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        bp = get_bond_proposal(ctx["bp"]["id"])
        # 100,000 + 0 - 100,000 == 0 is not > 0.
        resp = api.create_bond_sale(
            ctx["bp"]["id"],
            create_bond_sale_payload(
                "2027-Z", 100000, 0, 100000, "2027-12-01",
                expected_bond_proposal_version=bp["version"]),
            DT)
        validate_error(resp, ApiErrorId.ERR_NONPOSITIVE_NET_PROCEEDS, 422)
        sales, meta = validate_paginated(
            api.list_bond_sales(ctx["bp"]["id"], AU))
        assert sales == []
        assert meta["total_count"] == 0

    def test_duplicate_series_label_rejected(self, api):
        """PRD §3.8: "a `series_label` (for example, 2027-A) that is unique
        among the proposal's non-`CANCELLED` sales — a reused label fails with
        `ERR_DUPLICATE_SERIES_LABEL`".

        Design: Corner/validations/duplicate_series_label_rejected
        """
        ctx = setup_passed_proposal()
        bp_id = ctx["bp"]["id"]
        create_bond_sale(bp_id, "2027-A", 1000000, 0, 0, "2027-12-01")
        bp = get_bond_proposal(bp_id)
        resp = api.create_bond_sale(
            bp_id,
            create_bond_sale_payload(
                "2027-A", 500000, 0, 0, "2028-01-15",
                expected_bond_proposal_version=bp["version"]),
            DT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIES_LABEL, 409)

    def test_sale_date_beyond_authorization_window_rejected(self, api):
        """PRD §3.8: "Statute also bounds the calendar: the `sale_date` may be
        no later than 36 months after the proposal's `passed_at`, and a later
        sale is rejected with `ERR_AUTHORIZATION_LAPSED`."

        Design: Corner/validations/sale_date_beyond_authorization_window_rejected
        """
        # passed_at is the 2027-11-03 canvass; +36 months is 2030-11-03.
        ctx = setup_passed_proposal()
        bp = get_bond_proposal(ctx["bp"]["id"])
        resp = api.create_bond_sale(
            ctx["bp"]["id"],
            create_bond_sale_payload(
                "2030-A", 1000000, 0, 0, "2030-11-04",
                expected_bond_proposal_version=bp["version"]),
            DT)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_LAPSED, 409)

    def test_close_sale_before_sale_date_rejected(self, api):
        """PRD §3.8: "Closing the sale is permitted only on or after its
        `sale_date`; an early close fails with `ERR_SALE_NOT_YET_EFFECTIVE`."

        Design: Corner/validations/close_sale_before_sale_date_rejected
        """
        ctx = setup_passed_proposal()
        sale = create_bond_sale(ctx["bp"]["id"], "2027-A", 10000000, 150000,
                                80000, "2027-12-01")
        set_clock("2027-11-30T00:00:00Z", DT)  # one day before the sale date
        resp = api.close_bond_sale(sale["id"], DT)
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_YET_EFFECTIVE, 409)
        sales, _ = validate_paginated(
            api.list_bond_sales(ctx["bp"]["id"], AU))
        assert sales[0]["status"] == "PLANNED"

    def test_bond_sale_create_stale_proposal_version_returns_412(self, api):
        """PRD §2.8: "Creating a bond sale against a bond proposal requires a
        non-optional `expected_bond_proposal_version` carrying the proposal's
        `version` as the client last observed it. Multiple series sales
        against one passed proposal are legitimate, and each planned sale
        advances the proposal's `version`, so a create whose
        `expected_bond_proposal_version` no longer matches the proposal's
        current `version` is operating on a stale view of the proposal's
        remaining authorization and is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/bond_sale_create_stale_proposal_version_returns_412
        """
        ctx = setup_passed_proposal()
        bp_id = ctx["bp"]["id"]
        bp = get_bond_proposal(bp_id)
        observed = bp["version"]
        validate_success(api.create_bond_sale(
            bp_id,
            create_bond_sale_payload(
                "2027-A", 1000000, 0, 0, "2027-12-01",
                expected_bond_proposal_version=observed),
            DT), 201)
        # The first sale advanced the proposal's version: the token is stale.
        resp = api.create_bond_sale(
            bp_id,
            create_bond_sale_payload(
                "2027-B", 500000, 0, 0, "2028-01-15",
                expected_bond_proposal_version=observed),
            DT)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        sales, meta = validate_paginated(api.list_bond_sales(bp_id, AU))
        assert meta["total_count"] == 1
        assert sales[0]["series_label"] == "2027-A"
