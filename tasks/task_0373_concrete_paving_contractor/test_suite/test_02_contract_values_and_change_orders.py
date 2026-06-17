"""Contract-value figures (provisional vs committed), the change-order revision
cycle, and OCC on change-order approval. Covers §3.3, §3.10, §2.7.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_approved_project,
    submit_change_order, review_change_order, approve_change_order,
    submit_review_approve_change_order, project_version,
    create_change_order_payload, approve_change_order_payload,
    make_finance_officer_headers,
    TEST_USERS, COMBO_840_SEGMENTS,
)

PM = TEST_USERS["project_manager_headers"]


class TestProvisionalVsCommitted:
    """Provisional counts UNDER_REVIEW; committed counts only APPROVED."""

    def test_provisional_includes_under_review_committed_excludes(self, api):
        """PRD §3.3: "The provisional contract value is forward-looking: it is the
        project's base_contract_amount plus the sum of delta_amount over every
        change order whose status is UNDER_REVIEW or APPROVED, rounded to two
        decimal places."
        PRD §3.3: "The committed contract value is the conservative, billable
        reading: it is the base_contract_amount, then each APPROVED change order's
        delta_amount added in created_at ascending order, with the running total
        rounded to two decimal places."

        Design: Difficulty/dual_variant_calc/contract_value_provisional_vs_committed_variant
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Drive A")
        assert proj["base_contract_amount"] == 12452.50
        # One APPROVED +1500.00
        submit_review_approve_change_order(proj["id"], "add curb", 1500.00, "fin_1")
        # One UNDER_REVIEW -300.00
        co2 = submit_change_order(proj["id"], "remove drain", -300.00, "fin_1")
        review_change_order(co2["id"], "fin_1")

        project = get_success_data(api.get_project(proj["id"], PM))
        # provisional = 12452.50 + 1500.00 - 300.00 = 13652.50 (includes UNDER_REVIEW)
        assert project["provisional_contract_value"] == 13652.50
        # committed = 12452.50 + 1500.00 = 13952.50 (APPROVED only)
        assert project["committed_contract_value"] == 13952.50

    def test_provisional_exceeds_committed_while_review_open(self, api):
        """PRD §3.3: "Because it counts reviews in flight as if they will land, it
        can exceed the committed figure while reviews are open."

        Design: Difficulty/dual_variant_calc/contract_value_provisional_vs_committed_variant
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Drive B")
        submit_review_approve_change_order(proj["id"], "add curb", 1500.00, "fin_1")
        co2 = submit_change_order(proj["id"], "remove drain", -300.00, "fin_1")
        review_change_order(co2["id"], "fin_1")
        project = get_success_data(api.get_project(proj["id"], PM))
        # The in-flight UNDER_REVIEW order is negative, so committed (approved-only)
        # strictly exceeds the forward-looking provisional figure here.
        assert project["committed_contract_value"] == 13952.50
        assert project["provisional_contract_value"] == 13652.50
        assert project["committed_contract_value"] != project["provisional_contract_value"]

    def test_committed_chronological_two_approved(self, api):
        """PRD §3.3: "The committed contract value is the conservative, billable
        reading: it is the base_contract_amount, then each APPROVED change order's
        delta_amount added in created_at ascending order, with the running total
        rounded to two decimal places."

        Design: Corner/calculations/committed_chronological_order_two_approved
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Chron")
        submit_review_approve_change_order(proj["id"], "co1", 1500.00, "fin_2")
        submit_review_approve_change_order(proj["id"], "co2", 800.50, "fin_2")

        project = get_success_data(api.get_project(proj["id"], PM))
        assert project["committed_contract_value"] == 14753.00
        assert project["provisional_contract_value"] == 14753.00


class TestChangeOrderRevisionCycle:
    """SUBMITTED -> UNDER_REVIEW -> REVISION_REQUESTED -> SUBMITTED -> UNDER_REVIEW."""

    def test_revision_cycle_reenters_review_with_new_delta(self, api):
        """PRD §3.10: "A REVISION_REQUESTED order can be resubmitted, which returns
        it to SUBMITTED, updates its delta_amount and delta_sqft from the new
        request, and re-stamps submitted_by_user_id with the resubmitting
        officer's X-User-ID for another review round."
        PRD §3.10: "Beginning review moves a SUBMITTED change order to
        UNDER_REVIEW, which brings the order into the forward-looking provisional
        sum and so recomputes the project's provisional_contract_value."

        Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_loop
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Cyc A")
        co = submit_change_order(proj["id"], "scope tweak", 1000.00, "fin_1")
        review_change_order(co["id"], "fin_1")
        get_success_data(api.request_revision_change_order(co["id"],
                         make_finance_officer_headers("fin_1")))
        get_success_data(api.resubmit_change_order(co["id"], {"delta_amount": 2200.00},
                         make_finance_officer_headers("fin_1")))
        reviewed = get_success_data(api.start_review_change_order(co["id"],
                   make_finance_officer_headers("fin_1")))
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["delta_amount"] == 2200.00

    def test_request_revision_moves_under_review_order_to_revision_requested(self, api):
        """PRD §3.10: "Requesting a revision moves the order to REVISION_REQUESTED,
        removing it from the provisional sum and recomputing
        provisional_contract_value."

        Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_loop
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Cyc B")
        co = submit_change_order(proj["id"], "scope tweak", 1000.00, "fin_1")
        review_change_order(co["id"], "fin_1")
        revised = get_success_data(api.request_revision_change_order(
            co["id"], make_finance_officer_headers("fin_1")))
        assert revised["status"] == "REVISION_REQUESTED"

    def test_provisional_conserved_review_then_revision(self, api):
        """PRD §3.10: "Beginning review moves a SUBMITTED change order to
        UNDER_REVIEW, which brings the order into the forward-looking provisional
        sum and so recomputes the project's provisional_contract_value."
        PRD §3.10: "Requesting a revision moves the order to REVISION_REQUESTED,
        removing it from the provisional sum and recomputing
        provisional_contract_value."

        Design: Difficulty/compensating_invariant/provisional_contract_value_conserved_review_then_revision
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Inv A")
        assert proj["base_contract_amount"] == 12452.50
        co = submit_change_order(proj["id"], "extra", 1000.00, "fin_1")
        review_change_order(co["id"], "fin_1")
        mid = get_success_data(api.get_project(proj["id"], PM))
        assert mid["provisional_contract_value"] == 13452.50  # +1000.00 in flight

        get_success_data(api.request_revision_change_order(co["id"],
                         make_finance_officer_headers("fin_1")))
        after = get_success_data(api.get_project(proj["id"], PM))
        # Compensating: provisional restored to base, no drift.
        assert after["provisional_contract_value"] == 12452.50
        assert after["committed_contract_value"] == 12452.50

    def test_committed_unchanged_by_review_revision_cycle(self, api):
        """PRD §3.3: "The committed contract value is the conservative, billable
        reading: it is the base_contract_amount, then each APPROVED change order's
        delta_amount added in created_at ascending order, with the running total
        rounded to two decimal places."

        Design: Difficulty/compensating_invariant/provisional_contract_value_conserved_review_then_revision
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Inv B")
        co = submit_change_order(proj["id"], "extra", 1000.00, "fin_1")
        review_change_order(co["id"], "fin_1")
        get_success_data(api.request_revision_change_order(
            co["id"], make_finance_officer_headers("fin_1")))
        after = get_success_data(api.get_project(proj["id"], PM))
        # The change order never reached APPROVED, so committed stays at base.
        assert after["committed_contract_value"] == 12452.50


class TestChangeOrderApproveOcc:
    def test_approve_with_stale_project_version_rejected(self, api):
        """PRD §2.7: "When a FinanceOfficer approves a change order, the request
        must carry expected_project_version matching the project's current
        version."
        PRD §2.7: "The approval is therefore refused with ERR_STALE_PROJECT_VERSION
        (HTTP 412) when the supplied version no longer matches."

        Design: Corner/cross_cutting_complexity_layers/occ_change_order_approve_stale
        """
        proj, est = create_approved_project(
            segments=[dict(label="s", area_sqft=400, thickness_in=4, reinforcement="REBAR")],
            site_name="Occ1")
        co1 = submit_change_order(proj["id"], "co1", 500.00, "fin_6")
        review_change_order(co1["id"], "fin_6")
        stale_version = project_version(proj["id"])
        # A second change-order submit bumps the project version, making stale_version stale.
        submit_change_order(proj["id"], "co2", 200.00, "fin_6")

        res = api.approve_change_order(
            co1["id"], approve_change_order_payload(stale_version),
            make_finance_officer_headers("fin_6"))
        validate_error(res, "ERR_STALE_PROJECT_VERSION")
