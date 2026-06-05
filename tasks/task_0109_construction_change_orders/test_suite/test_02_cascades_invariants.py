"""Cascade-depth and conservation-invariant tests (Difficulty queue:
transitive_cascade, compensating_invariant)."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    OWNER, CONTRACTOR, ARCHITECT,
    JAN,
    create_pay_application, add_pay_app_line, submit_pay_application,
    get_project_version, create_retention_release,
    assert_retainage_held_equals_sov_sum, assert_revised_sum_equals_sov_sum,
)
from test_helpers import fixtures as fx


def _active_sov_lines(api, project_id):
    """Fetch all ACTIVE SOV lines for a project via the list endpoint."""
    resp = api.list_sov_lines(OWNER, params={"project_id": project_id, "status": "ACTIVE",
                                             "limit": 100})
    data, _ = validate_paginated(resp)
    return data


# ===========================================================================
# Rule: transitive_cascade
# ===========================================================================
class TestPayAppCertifyCascadeToSovThenProject:
    """Design: Difficulty/transitive_cascade/payapp_certify_cascade_sovline_then_project_depth3"""

    def test_certify_writes_retainage_back_to_each_sov_line(self, api):
        """PRD §3.4: "its retainage_withheld_to_date_cents is increased by the pay-app
        line's line_retainage_cents."

        Design: Difficulty/transitive_cascade/payapp_certify_cascade_sovline_then_project_depth3
        """
        project, sov1, sov2, pay_app = fx.setup_certified_two_line_project()
        s1 = validate_success(api.get_sov_line(sov1["id"], OWNER), 200)
        s2 = validate_success(api.get_sov_line(sov2["id"], OWNER), 200)
        # 001: 0.10 * 300000 = 30000; 002: 0.10 * (100000 + 50000) = 15000.
        assert s1["retainage_withheld_to_date_cents"] == 30000
        assert s2["retainage_withheld_to_date_cents"] == 15000

    def test_certify_recomputes_project_rollups_and_bumps_version(self, api):
        """PRD §3.4: "the project's total_completed_and_stored_cents and retainage_held_cents
        are recomputed from its lines, and Project.version is incremented by one."

        Design: Difficulty/transitive_cascade/payapp_certify_cascade_sovline_then_project_depth3
        """
        project, sov1, sov2, pay_app = fx.setup_certified_two_line_project()
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        assert proj["retainage_held_cents"] == 45000
        assert proj["total_completed_and_stored_cents"] == 450000
        # Project started at version 1; certify bumped it to 2.
        assert proj["version"] == 2


class TestChangeOrderApproveCascadeToSovThenRevisedSum:
    """Design: Difficulty/transitive_cascade/change_order_approve_cascade_sovline_then_revised_sum_depth3"""

    def _approve_co_with_adjust_and_add(self, api):
        project, sov1, sov2, co = fx.setup_submitted_change_order(
            change_order_amount_cents=150_000,
            line_edits=[
                {"action": "ADJUST", "item_no": "001", "scheduled_value_delta_cents": 100_000},
                {"action": "ADD", "item_no": "003", "description": "Sitework",
                 "scheduled_value_delta_cents": 50_000},
            ],
        )
        pv_cur = get_project_version(project["id"])
        validate_success(
            api.approve_change_order(co["id"], {"expected_project_version": pv_cur}, OWNER),
            200,
        )
        return project, sov1, sov2

    def test_approve_applies_line_edits_to_sov_lines(self, api):
        """PRD §3.2: "each ADD creates a new ACTIVE SovLine whose scheduled value is the
        edit's scheduled_value_delta_cents ...; each ADJUST adds the edit's
        scheduled_value_delta_cents to the named line's scheduled_value_cents."

        Design: Difficulty/transitive_cascade/change_order_approve_cascade_sovline_then_revised_sum_depth3
        """
        project, sov1, sov2 = self._approve_co_with_adjust_and_add(api)
        s1 = validate_success(api.get_sov_line(sov1["id"], OWNER), 200)
        assert s1["scheduled_value_cents"] == 700000  # 600000 + 100000 ADJUST.
        lines = _active_sov_lines(api, project["id"])
        added = [l for l in lines if l["item_no"] == "003"]
        assert len(added) == 1 and added[0]["scheduled_value_cents"] == 50000

    def test_approve_recomputes_revised_contract_sum(self, api):
        """PRD §3.2: "the project's revised_contract_sum_cents is recomputed as the
        original_contract_sum_cents plus the sum of change_order_amount_cents over every
        change order on the project now in APPROVED status".

        Design: Difficulty/transitive_cascade/change_order_approve_cascade_sovline_then_revised_sum_depth3
        """
        project, sov1, sov2 = self._approve_co_with_adjust_and_add(api)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        assert proj["revised_contract_sum_cents"] == 1150000


# ===========================================================================
# Rule: compensating_invariant
# ===========================================================================
class TestRetainageConservationCertifyThenRelease:
    """Design: Difficulty/compensating_invariant/retainage_conservation_certify_then_release"""

    def _certify_then_release_40000(self, api):
        project, sov1, sov2, pay_app, release = fx.setup_release_requested(40_000)
        pv_cur = get_project_version(project["id"])
        validate_success(
            api.approve_retention_release(
                release["id"], {"expected_project_version": pv_cur}, OWNER
            ),
            200,
        )
        return project, sov1, sov2

    def test_release_draws_down_held_to_expected_remainder(self, api):
        """PRD §3.8: "After the waterfall the project's retainage_held_cents is recomputed
        as the sum of retainage_withheld_to_date_cents over its active lines".

        Design: Difficulty/compensating_invariant/retainage_conservation_certify_then_release
        """
        project, sov1, sov2 = self._certify_then_release_40000(api)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        # held 45000 - 40000 release = 5000.
        assert proj["retainage_held_cents"] == 5000
        s1 = validate_success(api.get_sov_line(sov1["id"], OWNER), 200)
        s2 = validate_success(api.get_sov_line(sov2["id"], OWNER), 200)
        # Waterfall ascending item_no: 001 (30000) drawn fully, 002 drawn 10000 -> 5000 left.
        assert s1["retainage_withheld_to_date_cents"] == 0
        assert s2["retainage_withheld_to_date_cents"] == 5000

    def test_held_equals_sov_retainage_sum_no_drift(self, api):
        """PRD §2.5: "The retainage_held_cents is the project-wide roll-up of retainage
        currently withheld across schedule-of-values lines, net of any retention released."

        Design: Difficulty/compensating_invariant/retainage_conservation_certify_then_release
        """
        project, sov1, sov2 = self._certify_then_release_40000(api)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        lines = _active_sov_lines(api, project["id"])
        assert_retainage_held_equals_sov_sum(proj, lines)
        assert proj["retainage_held_cents"] == 5000


class TestContractSumConservationOnChangeOrderApprove:
    """Design: Difficulty/compensating_invariant/contract_sum_conservation_change_order_approve"""

    def _approve_balanced_co(self, api):
        project, sov1, sov2, co = fx.setup_submitted_change_order(
            change_order_amount_cents=150_000,
            line_edits=[
                {"action": "ADJUST", "item_no": "001", "scheduled_value_delta_cents": 100_000},
                {"action": "ADD", "item_no": "003", "description": "Sitework",
                 "scheduled_value_delta_cents": 50_000},
            ],
        )
        pv_cur = get_project_version(project["id"])
        validate_success(
            api.approve_change_order(co["id"], {"expected_project_version": pv_cur}, OWNER),
            200,
        )
        return project, sov1, sov2

    def test_revised_sum_matches_target_after_balanced_co(self, api):
        """PRD §3.2: "the sum of scheduled_value_delta_cents across the edits exactly equals
        the change order's change_order_amount_cents (else ERR_LINE_EDITS_UNBALANCED, HTTP 422)."

        Design: Difficulty/compensating_invariant/contract_sum_conservation_change_order_approve
        """
        project, sov1, sov2 = self._approve_balanced_co(api)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        assert proj["revised_contract_sum_cents"] == 1150000

    def test_revised_sum_equals_active_sov_scheduled_value_sum(self, api):
        """PRD §3.1: "the invariant the system maintains is that the sum of
        scheduled_value_cents across the non-deleted lines equals the project's
        revised_contract_sum_cents."

        Design: Difficulty/compensating_invariant/contract_sum_conservation_change_order_approve
        """
        project, sov1, sov2 = self._approve_balanced_co(api)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        lines = _active_sov_lines(api, project["id"])
        assert_revised_sum_equals_sov_sum(proj, lines)
        assert proj["revised_contract_sum_cents"] == 1150000
