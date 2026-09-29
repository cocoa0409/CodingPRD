"""Optimistic concurrency on the two authoring calls that echo the project version."""
import pytest

from test_helpers import (
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import change_order_payload, trust_fund_claim_payload
from test_helpers.test_users import COMPLIANCE_OFFICER, LSP_DRAFTER


class TestClaimCreateVersionFreshness:
    #: The interim application, small enough to stay inside the first cap tier.
    INTERIM_CENTS = 300000
    #: The close-out application.
    FINAL_CENTS = 900000

    def test_a_close_out_claim_replaying_the_pre_interim_version_is_rejected(self, api):
        """PRD §2.8: "Creating a `TrustFundClaim` likewise requires `expected_project_version`, and a value that does not equal the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). A close-out claim withdraws the project's open interim claim as a side effect, so it must be filed against a current project view; a stale value means the claimed costs were copied from a project snapshot that a subsequent change-order approval has already replaced."
        PRD §3.9: "The claim is created in `DRAFT`, its `state_code` is snapshotted from the project's property, the project's `version` is incremented by 1, and the full eligibility breakdown is computed."
        PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation."
        PRD §3.9: "Every `PRELIMINARY_ESTIMATE` claim on the same project whose `status` is `DRAFT`, `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` is transitioned to `WITHDRAWN`, and the code `SUPERSEDED_BY_FINAL_SETTLEMENT` is appended to that claim's `eligibility_findings`."

        Design: Corner/cross_cutting_complexity_layers/occ_final_claim_create_with_stale_project_version_is_rejected
        """
        ctx = fx.project_cleared()
        project_id = ctx["project"]["id"]
        assert fx.read_project(project_id)["status"] == "CLEARED", (
            "a clean confirmation result must leave the project clear before any "
            "claim is filed"
        )

        observed_version = fx.project_version(project_id, COMPLIANCE_OFFICER)
        interim = fx.create_claim(
            project_id,
            observed_version,
            variant="PRELIMINARY_ESTIMATE",
            claimed_costs_cents=self.INTERIM_CENTS,
        )
        assert interim["eligible_amount_cents"] == 239500, (
            "300,000 capped at 4,000,000, less the 50,000 New Jersey deductible, "
            f"less the 10,500-cent fee is 239,500, got {interim['eligible_amount_cents']}"
        )

        stale = api.create_trust_fund_claim(
            trust_fund_claim_payload(
                project_id,
                observed_version,
                variant="FINAL_SETTLEMENT",
                claimed_costs_cents=self.FINAL_CENTS,
            ),
            COMPLIANCE_OFFICER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)

        version_after_interim = fx.project_version(project_id, COMPLIANCE_OFFICER)
        assert version_after_interim == observed_version + 1, (
            "filing the interim application advanced the project by exactly one "
            f"version, from {observed_version}, got {version_after_interim}"
        )

        final = validate_success(
            api.create_trust_fund_claim(
                trust_fund_claim_payload(
                    project_id,
                    version_after_interim,
                    variant="FINAL_SETTLEMENT",
                    claimed_costs_cents=self.FINAL_CENTS,
                ),
                COMPLIANCE_OFFICER,
            ),
            201,
        )
        assert final["eligible_amount_cents"] == 818500, (
            "900,000 less the 50,000 deductible, capped, less the 31,500-cent fee is "
            f"818,500, got {final['eligible_amount_cents']}"
        )
        assert final["status"] == "DRAFT", (
            f"the accepted close-out application opens in DRAFT, got {final['status']}"
        )

        version_after_final = fx.project_version(project_id, COMPLIANCE_OFFICER)
        assert version_after_final == version_after_interim + 1, (
            "the second accepted create advanced the project by exactly one more "
            f"version, from {version_after_interim}, got {version_after_final}"
        )

        withdrawn = fx.read_claim(interim["id"])
        assert withdrawn["status"] == "WITHDRAWN", (
            "the close-out application supersedes the interim one, got "
            f"{withdrawn['status']}"
        )
        assert "SUPERSEDED_BY_FINAL_SETTLEMENT" in withdrawn["eligibility_findings"], (
            "the withdrawal reason is recorded on the interim application, got "
            f"{withdrawn['eligibility_findings']}"
        )

        _, meta = validate_paginated(
            api.list_trust_fund_claims(
                COMPLIANCE_OFFICER, params={"tank_project_id": project_id}
            )
        )
        assert meta["total_count"] == 2, (
            "the refused create filed nothing, so only the two accepted "
            f"applications exist, got {meta['total_count']}"
        )


class TestChangeOrderCreateVersionFreshness:
    def test_a_second_draft_replaying_the_pre_draft_version_is_rejected(self, api):
        """PRD §2.8: "Creating a `RemediationChangeOrder` requires `expected_project_version` in the request body. If that value does not equal the target project's current `version`, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The rule exists because a change order may legitimately supersede a prior approved change order, and the author's scope arithmetic is only sound if it was derived from the project's current approved scope and cost; a stale value means that arithmetic rests on superseded data."
        PRD §3.7: "The row is created in `DRAFT` with `requested_by_user_id` set from `X-User-ID`, the project's `version` is incremented by 1, and the project's blocker list is recomputed and now names `OPEN_CHANGE_ORDER`."
        PRD §3.7: "The project's `approved_scope_cubic_yards` is always its `baseline_scope_cubic_yards` plus the sum of `additional_cubic_yards` over the project's change orders whose `status` is `APPROVED`."

        Design: Corner/cross_cutting_complexity_layers/occ_change_order_create_with_stale_project_version_is_rejected
        """
        ctx = fx.project_remediation_active_gross(
            sample_point="CONFIRMATION_FLOOR", depth_inches=84
        )
        project_id = ctx["project"]["id"]
        assert ctx["project"]["status"] == "REMEDIATION_ACTIVE", (
            "a gross result must open remediation scoping, got "
            f"{ctx['project']['status']}"
        )

        observed_version = fx.project_version(project_id, LSP_DRAFTER)
        first = fx.create_change_order(
            project_id,
            observed_version,
            additional_cubic_yards=4.0,
            unit_rate_cents=1000,
        )

        stale = api.create_change_order(
            change_order_payload(
                project_id,
                observed_version,
                additional_cubic_yards=2.0,
                unit_rate_cents=1000,
            ),
            LSP_DRAFTER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)

        version_after_first = fx.project_version(project_id, LSP_DRAFTER)
        assert version_after_first == observed_version + 1, (
            "drafting the first change order advanced the project by exactly one "
            f"version, from {observed_version}, got {version_after_first}"
        )

        second = validate_success(
            api.create_change_order(
                change_order_payload(
                    project_id,
                    version_after_first,
                    additional_cubic_yards=2.0,
                    unit_rate_cents=1000,
                ),
                LSP_DRAFTER,
            ),
            201,
        )

        version_after_second = fx.project_version(project_id, LSP_DRAFTER)
        assert version_after_second == version_after_first + 1, (
            "the accepted retry advanced the project by exactly one more version, "
            f"from {version_after_first}, got {version_after_second}"
        )

        assert fx.read_change_order(first["id"])["status"] == "DRAFT", (
            "the first draft is untouched by the refusal"
        )
        assert fx.read_change_order(second["id"])["status"] == "DRAFT", (
            f"the accepted retry opens in DRAFT, got {second['status']}"
        )

        _, meta = validate_paginated(
            api.list_change_orders(
                LSP_DRAFTER, params={"tank_project_id": project_id}
            )
        )
        assert meta["total_count"] == 2, (
            "the refused create wrote no row, so only the two accepted drafts "
            f"exist, got {meta['total_count']}"
        )

        project = fx.read_project(project_id)
        assert project["approved_scope_cubic_yards"] == pytest.approx(8.0, abs=0.01), (
            "neither draft has been approved, so the scope is still the baseline, "
            f"got {project['approved_scope_cubic_yards']}"
        )
