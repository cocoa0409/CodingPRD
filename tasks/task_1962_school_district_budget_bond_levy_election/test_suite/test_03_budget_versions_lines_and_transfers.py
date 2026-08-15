"""Budget versions, appropriation lines, and transfers: initial state,
derived totals, OCC on the fiscal year, the propose/return revision loop,
supersession, and the transfer conservation invariant (PRD §2.8, §2.10,
§3.2, §3.5)."""
from test_helpers import (
    ApiErrorId, assert_budget_line, assert_budget_version, assert_money,
    get_success_data, validate_error, validate_paginated, validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_budget_line_payload, create_budget_version_payload,
    create_transfer_payload,
)
from test_helpers.fixtures import (
    adopt, add_budget_line, add_projection, add_revenue_estimate,
    add_staffing_allocation, add_position, create_budget_version,
    create_hearing, create_open_fiscal_year, hold_hearing, propose,
    set_clock, setup_adopted_budget, setup_hearing_held_budget,
)
from test_helpers.test_users import TEST_USERS

BA = TEST_USERS["budget_analyst_headers"]
BM = TEST_USERS["business_manager_headers"]
BC = TEST_USERS["board_clerk_headers"]
AU = TEST_USERS["auditor_headers"]


def _fresh_budget_version(fy_id):
    """Create a budget version against the fiscal year's current version."""
    fy = get_success_data(api_client.get_fiscal_year(fy_id, AU))
    return get_success_data(api_client.create_budget_version(
        fy_id, create_budget_version_payload(fy["version"]), BA), 201)


class TestBudgetVersionCreation:
    def test_budget_version_initial_state_is_draft(self, api):
        """PRD §3.2: "The server assigns each version a `version_label` — v1,
        v2, and so on per fiscal year, in creation order — and the new version
        starts in `DRAFT` with `hearing_held_date` and `adopted_at` both
        null."

        Design: Corner/state_machines/budget_version_initial_state_is_draft
        """
        fy = create_open_fiscal_year()
        resp = api.create_budget_version(
            fy["id"], create_budget_version_payload(fy["version"]), BA)
        data = validate_success(resp, 201)
        assert_budget_version(data)
        assert data["status"] == "DRAFT"
        assert data["version_label"] == "v1"
        assert data["hearing_held_date"] is None
        assert data["adopted_at"] is None
        assert data["total_appropriations"] == 0

    def test_budget_version_create_stale_fiscal_year_version(self, api):
        """PRD §2.8: "Creating a budget version against a fiscal year requires
        a non-optional `expected_fiscal_year_version` carrying the fiscal
        year's `version` as the client last observed it. Because a successful
        create legitimately supersedes the currently adopted version and
        advances the fiscal year's `version`, a create whose
        `expected_fiscal_year_version` no longer matches the fiscal year's
        current `version` is operating on a stale view of the year and is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/budget_version_create_stale_fiscal_year_version_returns_412
        """
        fy = create_open_fiscal_year()
        observed = fy["version"]
        bv1 = validate_success(api.create_budget_version(
            fy["id"], create_budget_version_payload(observed), BA), 201)
        assert bv1["version_label"] == "v1"
        # The successful create advanced the fiscal year's version: the same
        # token is now stale.
        resp = api.create_budget_version(
            fy["id"], create_budget_version_payload(observed), BA)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        versions, meta = validate_paginated(
            api.list_budget_versions(fy["id"], AU))
        assert meta["total_count"] == 1

    def test_subresource_lists_reverse_reach_fk_children(self, api):
        """PRD §4 lists GET /district/fiscal-years/{id}/enrollment-projections,
        GET /district/fiscal-years/{id}/budget-versions, and GET
        /district/fiscal-years/{id}/bond-proposals as retrieval endpoints
        returning one array per parent; PRD §2.3: "Paginated list responses
        carry four pagination fields in the envelope's `meta` object:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/subresource_lists_reverse_reach_fk_children
        """
        fy = create_open_fiscal_year()
        ep = add_projection(fy["id"], "ELEMENTARY", 1200)
        bv = _fresh_budget_version(fy["id"])

        projections, _ = validate_paginated(
            api.list_enrollment_projections(fy["id"], AU))
        assert [row["id"] for row in projections] == [ep["id"]]

        versions, _ = validate_paginated(api.list_budget_versions(fy["id"], AU))
        assert [row["id"] for row in versions] == [bv["id"]]

        proposals, meta = validate_paginated(api.list_bond_proposals(fy["id"], AU))
        assert proposals == []
        assert meta["total_count"] == 0


class TestBudgetLinesAndTotals:
    def test_total_appropriations_recomputed_on_line_add(self, api):
        """PRD §3.2: "The version's `total_appropriations` is the running sum
        of the `appropriation_amount` over all of its lines, recomputed as
        lines are added or moved". PRD §2.10: "Consistency is immediate: no
        derived figure is ever left waiting for a later reconciliation pass".

        Design: Corner/endpoints/budget_version_total_appropriations_recomputed_on_line_add
        """
        fy = create_open_fiscal_year()
        bv = _fresh_budget_version(fy["id"])
        add_budget_line(bv["id"], appropriation_amount=12000000)
        add_budget_line(bv["id"], appropriation_amount=6000000,
                        fund_code="OPERATIONS", function_code="2500",
                        object_code="300")
        bv_now = validate_success(api.get_budget_version(bv["id"], AU), 200)
        assert_money(bv_now["total_appropriations"], 18000000.00,
                     "total_appropriations")

    def test_budget_line_create_on_proposed_version_rejected(self, api):
        """PRD §3.2: "Lines may only be added while the version is `DRAFT`;
        against a version in any other state the write fails with
        `ERR_BUDGET_VERSION_NOT_DRAFT`."

        Design: Corner/validations/budget_line_create_on_proposed_version_rejected
        """
        fy = create_open_fiscal_year()
        bv = _fresh_budget_version(fy["id"])
        propose(bv["id"])
        resp = api.create_budget_line(
            bv["id"], create_budget_line_payload(), BA)
        validate_error(resp, ApiErrorId.ERR_BUDGET_VERSION_NOT_DRAFT, 409)

    def test_propose_adopted_version_rejected_invalid_state(self, api):
        """PRD §3.2: "a `BoardClerk` proposes it — `DRAFT` → `PROPOSED`" — the
        propose trigger exists only from DRAFT, so proposing an ADOPTED
        version is the generic from-state violation (`ERR_INVALID_STATE`,
        PRD §2.9 stage 8).

        Design: Corner/state_machines/propose_adopted_version_rejected_invalid_state
        """
        ctx = setup_adopted_budget()
        resp = api.propose_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestTransfers:
    def test_transfer_between_lines_of_different_versions_rejected(self, api):
        """PRD §3.2: "The two identifiers must reference two distinct lines of
        this budget version — a pair drawn from different versions, or a line
        paired with itself, fails with `ERR_TRANSFER_LINE_MISMATCH` — and the
        `amount` may not exceed the source line's current
        `appropriation_amount`; when it does, the transfer fails with
        `ERR_TRANSFER_EXCEEDS_LINE`."

        Design: Corner/validations/transfer_between_lines_of_different_versions_rejected
        """
        fy = create_open_fiscal_year()
        bv1 = _fresh_budget_version(fy["id"])
        l1 = add_budget_line(bv1["id"], appropriation_amount=1000000)
        bv2 = _fresh_budget_version(fy["id"])
        l2 = add_budget_line(bv2["id"], appropriation_amount=500000,
                             fund_code="OPERATIONS", function_code="2500",
                             object_code="300")
        resp = api.create_transfer(
            bv1["id"], create_transfer_payload(l1["id"], l2["id"], 100), BA)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_LINE_MISMATCH, 422)

    def test_transfer_forward_conserves_total_appropriations(self, api):
        """PRD §3.2: "A transfer subtracts the amount from the source line's
        `appropriation_amount` and adds it to the destination line's,
        increments both lines' `version`, and leaves the version's
        `total_appropriations` unchanged. The response echoes `from_line_id`,
        `to_line_id`, and `amount`, and reports the resulting balances as
        `from_line_appropriation` and `to_line_appropriation`."

        Design: Difficulty/compensating_invariant/budget_transfer_conserves_total_appropriations
        """
        fy = create_open_fiscal_year()
        bv = _fresh_budget_version(fy["id"])
        l1 = add_budget_line(bv["id"], appropriation_amount=1000000)
        l2 = add_budget_line(bv["id"], appropriation_amount=500000,
                             fund_code="OPERATIONS", function_code="2500",
                             object_code="300")
        data = validate_success(api.create_transfer(
            bv["id"], create_transfer_payload(l1["id"], l2["id"], 250000),
            BA), 201)
        assert data["from_line_id"] == l1["id"]
        assert data["to_line_id"] == l2["id"]
        assert_money(data["amount"], 250000.00, "transfer amount")
        assert_money(data["from_line_appropriation"], 750000.00, "from line")
        assert_money(data["to_line_appropriation"], 750000.00, "to line")
        bv_now = validate_success(api.get_budget_version(bv["id"], AU), 200)
        assert_money(bv_now["total_appropriations"], 1500000.00,
                     "total_appropriations after forward transfer")

    def test_transfer_reverse_roundtrip_and_over_transfer_rejected(self, api):
        """PRD §3.2: "the `amount` may not exceed the source line's current
        `appropriation_amount`; when it does, the transfer fails with
        `ERR_TRANSFER_EXCEEDS_LINE`" and "A transfer subtracts the amount from
        the source line's `appropriation_amount` and adds it to the
        destination line's, increments both lines' `version`, and leaves the
        version's `total_appropriations` unchanged."

        Design: Difficulty/compensating_invariant/budget_transfer_conserves_total_appropriations
        """
        fy = create_open_fiscal_year()
        bv = _fresh_budget_version(fy["id"])
        l1 = add_budget_line(bv["id"], appropriation_amount=1000000)
        l2 = add_budget_line(bv["id"], appropriation_amount=500000,
                             fund_code="OPERATIONS", function_code="2500",
                             object_code="300")
        validate_success(api.create_transfer(
            bv["id"], create_transfer_payload(l1["id"], l2["id"], 250000),
            BA), 201)
        # Compensating reverse transfer restores both lines exactly.
        data = validate_success(api.create_transfer(
            bv["id"], create_transfer_payload(l2["id"], l1["id"], 250000),
            BA), 201)
        assert_money(data["from_line_appropriation"], 500000.00)
        assert_money(data["to_line_appropriation"], 1000000.00)
        # Over-transfer against the restored source line is rejected.
        resp = api.create_transfer(
            bv["id"], create_transfer_payload(l1["id"], l2["id"], 2000000),
            BA)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_EXCEEDS_LINE, 422)
        lines, _ = validate_paginated(api.list_budget_lines(bv["id"], AU))
        by_id = {row["id"]: row for row in lines}
        assert_money(by_id[l1["id"]]["appropriation_amount"], 1000000.00)
        assert_money(by_id[l2["id"]]["appropriation_amount"], 500000.00)
        bv_now = validate_success(api.get_budget_version(bv["id"], AU), 200)
        assert_money(bv_now["total_appropriations"], 1500000.00,
                     "total_appropriations after round trip")

    def test_immediate_visibility_after_mutation(self, api):
        """PRD §2.10: "Consistency is immediate: no derived figure is ever
        left waiting for a later reconciliation pass, and no child is ever
        left in a state its parent's state contradicts." PRD §3.2: a transfer
        "increments both lines' `version`".

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        fy = create_open_fiscal_year()
        bv = _fresh_budget_version(fy["id"])
        l1 = add_budget_line(bv["id"], appropriation_amount=1000000)
        l2 = add_budget_line(bv["id"], appropriation_amount=500000,
                             fund_code="OPERATIONS", function_code="2500",
                             object_code="300")
        validate_success(api.create_transfer(
            bv["id"], create_transfer_payload(l1["id"], l2["id"], 250000),
            BA), 201)
        lines, _ = validate_paginated(api.list_budget_lines(bv["id"], AU))
        by_id = {row["id"]: row for row in lines}
        assert_money(by_id[l1["id"]]["appropriation_amount"], 750000.00)
        assert_money(by_id[l2["id"]]["appropriation_amount"], 750000.00)
        assert by_id[l1["id"]]["version"] > l1["version"]
        assert by_id[l2["id"]]["version"] > l2["version"]


class TestProposeReturnRevisionLoop:
    def _proposed_with_held_hearing(self):
        """DRAFT budget -> PROPOSED -> hearing HELD on 2027-03-20."""
        return setup_hearing_held_budget()

    def test_return_from_hearing_held_clears_hearing_credit_then_repropose(
            self, api):
        """PRD §3.2: "Returning to draft remains available to the clerk from
        either later pre-adoption state: from `PROPOSED`, the return sweeps
        every still-`NOTICE_PUBLISHED` hearing of the version to `CANCELLED`;
        from `HEARING_HELD`, it additionally clears `hearing_held_date` back
        to null. Both returns land in `DRAFT` and increment the version's
        `version`."

        Design: Difficulty/non_linear_state_machine/budget_version_propose_return_revision_loop
        """
        ctx = self._proposed_with_held_hearing()
        bv_id = ctx["bv"]["id"]
        assert ctx["bv"]["status"] == "HEARING_HELD"
        # Stamped with the hearing's hearing_date; PRD pins the calendar
        # date, not the serialization.
        assert str(ctx["bv"]["hearing_held_date"]).startswith("2027-03-20")

        returned = validate_success(
            api.return_budget_version_to_draft(bv_id, BC), 200)
        assert returned["status"] == "DRAFT"
        assert returned["hearing_held_date"] is None

        # The cycle continues: DRAFT -> PROPOSED again.
        reproposed = validate_success(api.propose_budget_version(bv_id, BC), 200)
        assert reproposed["status"] == "PROPOSED"

    def test_return_from_proposed_cancels_pending_hearing_only(self, api):
        """PRD §3.2: "from `PROPOSED`, the return sweeps every
        still-`NOTICE_PUBLISHED` hearing of the version to `CANCELLED`" — a
        hearing already HELD is not in that set and remains HELD.
        PRD §3.5: "A clerk may also cancel a published hearing outright —
        `NOTICE_PUBLISHED` → `CANCELLED`".

        Design: Difficulty/non_linear_state_machine/budget_version_propose_return_revision_loop
        """
        ctx = self._proposed_with_held_hearing()
        bv_id = ctx["bv"]["id"]
        held_hearing_id = ctx["hearing"]["id"]
        # Cycle back to PROPOSED and schedule a second (pending) hearing.
        validate_success(api.return_budget_version_to_draft(bv_id, BC), 200)
        validate_success(api.propose_budget_version(bv_id, BC), 200)
        set_clock("2027-03-21T00:00:00Z", BC)
        pending = create_hearing(bv_id, venue="GYMNASIUM",
                                 hearing_date="2027-04-05")

        returned = validate_success(
            api.return_budget_version_to_draft(bv_id, BC), 200)
        assert returned["status"] == "DRAFT"

        hearings, _ = validate_paginated(api.list_hearings(bv_id, AU))
        by_id = {row["id"]: row for row in hearings}
        assert by_id[pending["id"]]["status"] == "CANCELLED"
        assert by_id[held_hearing_id]["status"] == "HELD"


class TestSupersedeCascade:
    def test_supersede_cascade_retires_prior_budget_version(self, api):
        """PRD §3.2: "Creation is itself a supersession event: if another
        version of the same fiscal year is currently `ADOPTED`, it is retired
        to `SUPERSEDED` with the full supersede cascade of §3.5, and the
        fiscal year's `version` increments." PRD §3.5: "the retired version's
        staffing allocations move `AUTHORIZED` → `SUPERSEDED`; each superseded
        allocation eliminates its positions, moving every position in
        `PROPOSED`, `OPEN`, or `FILLED` to `ELIMINATED`; and the fiscal year's
        `authorized_fte_total` and `open_position_count`, along with each
        allocation's `positions_fte_total`, are recomputed. The version's
        budget lines move `ADOPTED` → `SUPERSEDED`, and the retired version's
        `version` increments."

        Design: Corner/state_machines/supersede_cascade_retires_prior_budget_version
        """
        # Adopted v1 with one ELEMENTARY allocation (3.0 FTE) and one position.
        fy = create_open_fiscal_year()
        ep = add_projection(fy["id"], "ELEMENTARY", 1200)
        bv1 = _fresh_budget_version(fy["id"])
        add_budget_line(bv1["id"], appropriation_amount=1000)
        add_revenue_estimate(bv1["id"])
        sa = add_staffing_allocation(bv1["id"], "ELEMENTARY", ep["id"], 3.0)
        pos = add_position(sa["id"], "Teacher 1", 1.0, 64000)
        propose(bv1["id"])
        set_clock("2027-03-01T00:00:00Z", BC)
        h = create_hearing(bv1["id"], "BOARD_ROOM", "2027-03-20")
        set_clock("2027-03-20T09:00:00Z", BC)
        hold_hearing(h["id"])
        set_clock("2027-03-27T09:00:00Z", BC)
        adopt(bv1["id"])

        # Sanity: adoption opened the position and booked the FTE total.
        fy_mid = validate_success(api.get_fiscal_year(fy["id"], AU), 200)
        assert fy_mid["authorized_fte_total"] == 3.0
        assert fy_mid["open_position_count"] == 1

        # Creating v2 supersedes the ADOPTED v1 with the full cascade.
        bv2 = _fresh_budget_version(fy["id"])
        assert bv2["version_label"] == "v2"

        bv1_now = validate_success(api.get_budget_version(bv1["id"], AU), 200)
        assert bv1_now["status"] == "SUPERSEDED"
        sa_now = validate_success(api.get_staffing_allocation(sa["id"], AU), 200)
        assert sa_now["status"] == "SUPERSEDED"
        positions, _ = validate_paginated(api.list_positions(sa["id"], AU))
        assert positions[0]["status"] == "ELIMINATED"
        fy_now = validate_success(api.get_fiscal_year(fy["id"], AU), 200)
        assert fy_now["authorized_fte_total"] == 0
        assert fy_now["open_position_count"] == 0
